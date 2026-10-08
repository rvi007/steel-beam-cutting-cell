"""Saved plasma settings (beamcell/plasma_presets.py) and problem reports (beamcell/reports.py)."""
import shutil
import tempfile
import unittest

from beamcell import manual, plasma, plasma_presets as P, reports as R
from beamcell.planner import Plan
from beamcell.safety import SafetyController


class PlasmaPresets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_start_values_come_from_the_chart_for_web_and_flange(self):
        v = P.start_values("UB 305x165x40", "o2", "S355")
        self.assertEqual(v["name"], "UB 305x165x40 S355")
        self.assertEqual((v["web"]["thickness_mm"], v["flange"]["thickness_mm"]), (6.0, 10.2))
        self.assertEqual(v["web"]["speed_mm_min"], plasma.settings("cut", 6.0, "o2")["speed_mm_min"])

    def test_save_open_list_delete(self):
        v = P.start_values("UB 305x165x40")
        v["web"]["speed_mm_min"] = 3600
        v["rating"] = "good"
        saved = P.save(v, self.dir)
        self.assertEqual(P.load(saved["name"], self.dir)["web"]["speed_mm_min"], 3600)
        self.assertEqual([e["name"] for e in P.for_section("UB 305x165x40", self.dir)], ["UB 305x165x40 S355"])
        self.assertEqual(P.for_section("UC 203x203x46", self.dir), [])
        first = saved["created"]
        self.assertEqual(P.save(v, self.dir)["created"], first)       # saving again keeps when it was made
        P.delete(saved["name"], self.dir)
        self.assertEqual(P.entries(self.dir), [])
        with self.assertRaises(KeyError):
            P.load(saved["name"], self.dir)

    def test_bad_numbers_and_names_are_refused(self):
        v = P.start_values("UB 305x165x40")
        v["web"]["speed_mm_min"] = 0
        with self.assertRaises(ValueError):
            P.save(v, self.dir)
        v = P.start_values("UB 305x165x40")
        v["flange"]["cut_height_mm"] = "abc"
        with self.assertRaises(ValueError):
            P.save(v, self.dir)
        self.assertEqual(P.safe_name("../../etc/passwd"), "etc passwd")
        with self.assertRaises(ValueError):
            P.safe_name("  ")

    def test_the_plan_uses_the_saved_numbers(self):
        v = P.start_values("UB 305x165x40")
        v["web"]["speed_mm_min"] = 1000                          # much slower than the chart
        v["web"]["hole_speed_mm_min"] = 500
        preset = P.save(v, self.dir)
        bar, _ = manual.build("UB 305x165x40", 3000, [{"type": "hole", "face": "v", "x": 500, "d": 22}, {"type": "cut", "x": 1500}])
        chart, saved = Plan(bar).build(), Plan(bar, preset).build()
        self.assertGreater(saved.summary()["duration_s"], chart.summary()["duration_s"])
        hole = next(c["process"] for c in saved.cuts if c["process"]["feature"] == "hole" and c["process"]["thickness_mm"] == 6.0)
        self.assertEqual((hole["speed_mm_min"], hole["preset"]), (500, preset["name"]))
        self.assertEqual(saved.to_json()["process"]["preset"], preset["name"])


class Reports(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        R.close_incident()
        self.sc = SafetyController(log_path="")
        self.sc.on_stop = lambda code, text: R.record(code, text, {"job": self.sc.job and dict(self.sc.job)}, self.dir)
        self.sc.on_reset = R.close_incident

    def tearDown(self):
        R.close_incident()
        shutil.rmtree(self.dir)

    def run_job(self):
        self.sc.load_job("bar 1")
        self.sc.confirm_checklist()
        self.sc.reset()
        self.sc.tick("test")
        self.assertTrue(self.sc.start()[0])

    def test_no_report_without_a_job(self):
        self.sc.press_estop("screen")
        self.assertEqual(R.entries(self.dir), [])

    def test_stops_before_a_reset_are_one_report(self):
        self.run_job()
        self.sc.press_estop("screen")
        self.sc.set_input("gate_closed", False)
        self.sc.set_input("gate_closed", True)
        self.sc.release_estop("screen")
        self.sc.reset()                                   # closes the incident
        self.sc.tick("test")
        self.sc.start()
        self.sc.press_estop("panel")                      # a new stop: a new report
        rows = R.entries(self.dir)
        self.assertEqual(len(rows), 2)
        first = R.load(rows[-1]["id"], self.dir)
        self.assertIn("E-STOP", first["title"])
        self.assertEqual(first["job"]["name"], "bar 1")
        self.assertIn("Stops:", first["text"])

    def test_note_sent_delete(self):
        self.run_job()
        self.sc.press_estop("screen")
        rid = R.entries(self.dir)[0]["id"]
        self.assertEqual(R.add_note(rid, "gate light flickered", self.dir)["note"], "gate light flickered")
        self.assertIn("gate light flickered", R.load(rid, self.dir)["text"])
        self.assertTrue(R.mark_sent(rid, "GitHub issue", self.dir)["sent"].startswith("GitHub issue"))
        R.delete(rid, self.dir)
        self.assertEqual(R.entries(self.dir), [])
        with self.assertRaises(KeyError):
            R.load("../../config/cell", self.dir)

    def test_a_broken_report_never_stops_the_safety_code(self):
        def boom(code, text):
            raise OSError("disk full")
        self.sc.on_stop = boom
        self.run_job()
        self.sc.press_estop("screen")
        self.assertEqual(self.sc.state, "ESTOP")
        self.assertIn("problem report not saved", self.sc.events[0]["text"])


if __name__ == "__main__":
    unittest.main()


class MeasuringPass(unittest.TestCase):
    def test_the_cutter_measures_the_bar_before_any_cut(self):
        import numpy as np
        from beamcell.machine import BEAM_Y
        bar, _ = manual.build("UB 305x165x40", 6000, [{"type": "hole", "face": "v", "x": 800, "d": 22}, {"type": "cut", "x": 1500}])
        plan = Plan(bar).build()
        scan = plan.to_json()["scan"]
        self.assertLess(scan["t0"], scan["t1"])
        self.assertLessEqual(scan["t1"], min(c["t_on"] for c in plan.cuts))       # measured before the torch lights
        self.assertEqual([p["what"] for p in scan["passes"]], ["flange", "web"])    # both: the web too
        web = scan["passes"][1]
        tip, d = plan.cutter.tip(*plan.tc.at((web["t0"] + web["t1"]) / 2))
        self.assertAlmostEqual(d[2], 0.0, places=3)                                  # looking at the web from the side
        flange = scan["passes"][0]
        xs = []
        for t in np.linspace(flange["t0"], flange["t1"], 5):
            tip = plan.cutter.tip(*plan.tc.at(t))[0]
            self.assertAlmostEqual(tip[1], BEAM_Y, places=2)                         # straight above the bar
            xs.append(tip[0])
        self.assertGreater(xs[0] - xs[-1], 5.0)                                      # along (nearly) all of it
