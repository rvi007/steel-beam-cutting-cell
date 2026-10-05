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
