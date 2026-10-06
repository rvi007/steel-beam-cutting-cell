"""Plasma settings for each kind of cut, and the sensors / bar check."""
import unittest

from beamcell import plasma, sensors


class Plasma(unittest.TestCase):
    def test_amps_follow_thickness(self):
        self.assertEqual(plasma.settings("cut", 6)["amps"], 130)
        self.assertEqual(plasma.settings("cut", 20)["amps"], 170)
        self.assertEqual(plasma.settings("cut", 40)["amps"], 300)

    def test_thicker_is_slower_and_needs_longer_pierce(self):
        a, b = plasma.settings("hole", 6), plasma.settings("hole", 12)
        self.assertGreater(a["speed_mm_min"], b["speed_mm_min"])
        self.assertLess(a["pierce_delay_s"], b["pierce_delay_s"])

    def test_holes_are_slower_with_thc_off(self):
        cut, hole = plasma.settings("cut", 10), plasma.settings("hole", 10, hole_d=22)
        self.assertLess(hole["speed_mm_min"], cut["speed_mm_min"])
        self.assertEqual(hole["thc"], "off")
        self.assertEqual(cut["pierce_delay_s"], 0.0)            # edge start
        self.assertGreater(hole["pierce_delay_s"], 0.0)
        self.assertGreaterEqual(hole["pierce_height_mm"], 1.5 * hole["cut_height_mm"])

    def test_small_holes_must_be_drilled(self):
        s = plasma.settings("hole", 25, hole_d=18)
        self.assertTrue(any("drill" in w for w in s["warnings"]))
        self.assertFalse(plasma.settings("hole", 10, hole_d=22)["warnings"])

    def test_cope_has_corner_slowdown(self):
        s = plasma.settings("cope", 10)
        self.assertLess(s["corner_speed_mm_min"], s["speed_mm_min"])

    def test_pen_for_the_prototype(self):
        s = plasma.settings("hole", 10, "pen", 22)
        self.assertEqual(s["arc_voltage_v"], 0)
        self.assertFalse(s["warnings"])


class Sensors(unittest.TestCase):
    def test_two_cameras_and_every_group(self):
        st = sensors.status()
        ids = {s["id"] for s in st}
        self.assertTrue({"cam_cell", "cam_torch", "datum_laser", "profile_scanner", "torch_touch", "load_cell"} <= ids)
        self.assertEqual({s["group"] for s in st}, set(sensors.GROUPS))
        self.assertTrue(all(s["buy"] and s["where"] for s in st))

    def test_bar_check_within_tolerance(self):
        r = sensors.measure_bar("UB 305x165x40", 12000)
        self.assertTrue(r["ok"], r["checks"])
        self.assertTrue(r["simulated"])
        self.assertEqual(r, sensors.measure_bar("UB 305x165x40", 12000))   # repeatable

    def test_bar_check_catches_a_wrong_or_bent_bar(self):
        m = {"start_x": 2, "length": 12000, "depth": 310.0, "width": 165, "out_of_square": 1, "bow": 5}
        r = sensors.measure_bar("UB 305x165x40", 12000, m)
        self.assertFalse(r["ok"])
        self.assertFalse(next(c for c in r["checks"] if c["what"] == "depth (h)")["ok"])
        m.update(depth=303.4, bow=25)
        self.assertFalse(sensors.measure_bar("UB 305x165x40", 12000, m)["ok"])
        self.assertFalse(sensors.measure_bar("UB 305x165x40", 12000, dict(m, present=False))["ok"])

    def test_tolerances_bs_en_10034(self):
        from beamcell import sections as S
        t = sensors.tolerances(S.get("UB 305x165x40"), 12000)
        self.assertEqual(t["depth"], (-2, 4))
        self.assertAlmostEqual(t["bow"], 18.0)


class JobCheck(unittest.TestCase):
    """The bar on the bed is measured at Start and checked against the job."""

    def setUp(self):
        from beamcell import manual
        self.bar, _ = manual.build("UB 305x165x40", 6000, [{"type": "hole", "face": "v", "x": 800, "d": 22},
                                                           {"type": "hole", "face": "o", "x": 500, "y": 138.5, "d": 22},
                                                           {"type": "cut", "x": 1500}])

    def tearDown(self):
        sensors.SIM_BAR["mode"] = "ok"

    def test_the_right_bar_passes(self):
        r = sensors.job_check(self.bar)
        self.assertTrue(r["ok"], r["problems"])
        self.assertEqual(r["needed_mm"], 1500)
        self.assertTrue({"web thickness", "flange thickness", "length for this job"} <= {c["what"] for c in r["checks"]})

    def test_every_wrong_bar_is_refused_with_a_reason(self):
        expect = {"short": "short", "wrong_section": "Depth", "narrow_flange": "Flange width", "thin_flange": "Flange thickness",
                  "existing_hole": "hole", "bent": "bowed", "no_bar": "No bar"}
        for mode, word in expect.items():
            sensors.SIM_BAR["mode"] = mode
            r = sensors.job_check(self.bar)
            self.assertFalse(r["ok"], mode)
            self.assertTrue(any(word in p["text"] for p in r["problems"]), (mode, r["problems"]))
            self.assertTrue(all(p["fix"] for p in r["problems"]))

    def test_a_hole_at_the_edge_fails_on_a_narrower_real_flange(self):
        m = sensors.simulated_reading(self.bar.parts[0].sec, 6000, 1500)
        m["width"] = 164.0                                   # 1 mm narrow: inside the rolling tolerance
        r = sensors.job_check(self.bar, m)
        self.assertFalse(r["ok"])
        self.assertIn("edge distance", r["problems"][0]["text"])

    def test_thickness_tolerances(self):
        self.assertEqual(sensors.thickness_tolerance(10.2, True), (-1.5, 2.5))
        self.assertEqual(sensors.thickness_tolerance(6.0, False), (-0.7, 0.7))
