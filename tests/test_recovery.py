"""Carrying on after a stop or a power cut (beamcell/recovery.py) and the scan back at Start."""
import os
import shutil
import tempfile
import unittest

from beamcell import manual, recovery, sensors


class Recovery(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "recovery.json")
        self.job = {"name": "bar 1", "started": True, "state": "running", "runs": 1,
                    "request": {"endpoint": "/api/manual/plan", "body": {"section": "UB 305x165x40", "length": 3000, "cuts": []}}}
        recovery._last["t"] = 0

    def tearDown(self):
        shutil.rmtree(self.dir)
        sensors.SIM_BAR["mode"] = "ok"

    def test_progress_is_saved_and_survives(self):
        self.assertTrue(recovery.save(self.job, {"t_exact": 42.5, "op": "M1: hole 2", "done": 3, "total": 9}, "RUNNING", path=self.path))
        r = recovery.summary(self.path)
        self.assertEqual((r["t"], r["op"], r["done"], r["total"]), (42.5, "M1: hole 2", 3, 9))
        self.assertIn("power", r["why"])                         # it was running when it was last saved
        self.assertEqual(r["job"]["request"]["endpoint"], "/api/manual/plan")

    def test_a_stop_is_saved_at_once_and_named(self):
        recovery.save(self.job, {"t_exact": 10}, "RUNNING", path=self.path)
        recovery.save(self.job, {"t_exact": 11}, "STOPPED", last_stop="10:02:03 E-STOP pressed", force=True, path=self.path)
        self.assertEqual(recovery.summary(self.path)["why"], "10:02:03 E-STOP pressed")

    def test_only_jobs_under_way_and_never_backwards(self):
        self.assertFalse(recovery.save(dict(self.job, started=False), {"t_exact": 1}, "READY", path=self.path))
        self.assertFalse(recovery.save(dict(self.job, state="finished"), {"t_exact": 1}, "READY", path=self.path))
        recovery.save(self.job, {"t_exact": 50, "op": "B", "done": 4}, "RUNNING", path=self.path)
        recovery._last["t"] = 0
        recovery.save(self.job, {"t_exact": 20, "op": "A", "done": 1}, "RUNNING", path=self.path)   # going back to resume
        self.assertEqual(recovery.load(self.path)["t"], 50)
        recovery.clear(self.path)
        self.assertIsNone(recovery.load(self.path))

    def test_scan_back_finds_the_cuts_or_refuses_a_moved_bar(self):
        bar, _ = manual.build("UB 305x165x40", 3000, [{"type": "hole", "face": "v", "x": 500, "d": 22}, {"type": "cut", "x": 1500}])
        r = sensors.job_check(bar, resume={"done": 2, "op": "M1: cut-off"})
        self.assertTrue(r["ok"], r["problems"])
        self.assertTrue(r["scan_back"]["ok"])
        sensors.SIM_BAR["mode"] = "bar_moved"
        r = sensors.job_check(bar, resume={"done": 2})
        self.assertFalse(r["ok"])
        self.assertIn("moved", r["problems"][0]["what"])


if __name__ == "__main__":
    unittest.main()
