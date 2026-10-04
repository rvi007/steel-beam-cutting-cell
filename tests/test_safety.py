"""The safety controller must behave like a real machine's safety circuit."""
import copy
import time
import unittest

from beamcell.config import DEFAULTS
from beamcell.gpio_inputs import GpioInputs
from beamcell.safety import SafetyController, safety_distance


class FakeCamera:
    def __init__(self):
        self.s = {"enabled": True, "has_frame": True, "frame_age": 0.1, "in_warning": False, "in_danger": False, "people": 0}

    def status(self):
        return dict(self.s)


def make(**changes):
    cfg = copy.deepcopy(DEFAULTS["safety"])
    cfg.update(changes)
    cam = FakeCamera()
    return SafetyController(vision=cam, config=cfg, log_path=""), cam


def run(sc):
    sc.tick()
    assert sc.reset()[0], sc.status()["reset_blockers"]
    sc.confirm_checklist()
    ok, why = sc.start()
    assert ok, why
    return sc.tick()


class Basics(unittest.TestCase):
    def test_power_on_needs_reset_and_checklist(self):
        sc, _ = make()
        self.assertEqual(sc.status()["state"], "NOT_RESET")
        ok, why = sc.start()
        self.assertFalse(ok)
        self.assertIn("press Reset first", why)
        sc.reset()
        ok, why = sc.start()
        self.assertFalse(ok)
        self.assertIn("confirm the pre-start checklist", why)
        st = run(sc)
        self.assertTrue(st["may_move"])
        self.assertEqual(st["speed_factor"], 1.0)
        self.assertTrue(st["lamps"]["green"])

    def test_estop_latches_and_needs_release_then_reset_then_start(self):
        sc, _ = make()
        run(sc)
        sc.press_estop("panel")
        st = sc.tick()
        self.assertEqual(st["state"], "ESTOP")
        self.assertFalse(st["may_move"])
        self.assertFalse(st["torch_allowed"])
        self.assertEqual(st["stop_category"], 0)
        self.assertTrue(st["lamps"]["red"])
        self.assertFalse(sc.reset()[0])                       # still pressed
        sc.release_estop("panel")
        self.assertFalse(sc.tick()["may_move"])               # releasing never restarts
        self.assertTrue(sc.reset()[0])
        self.assertFalse(sc.tick()["may_move"])               # reset never restarts either
        self.assertTrue(sc.start()[0])
        self.assertTrue(sc.tick()["may_move"])

    def test_two_estops_both_must_be_released(self):
        sc, _ = make()
        run(sc)
        sc.press_estop("panel")
        sc.press_estop("button")
        sc.release_estop("panel")
        self.assertFalse(sc.reset()[0])
        sc.release_estop("button")
        self.assertTrue(sc.reset()[0])

    def test_gate_and_light_curtain(self):
        for name, code in (("gate_closed", "GATE"), ("curtain_clear", "CURTAIN")):
            sc, _ = make()
            run(sc)
            sc.set_input(name, False)
            st = sc.tick()
            self.assertEqual(st["state"], "FAULT")
            self.assertEqual(st["stop_category"], 1)
            self.assertIn(code, [f["code"] for f in st["latched"]])
            self.assertFalse(sc.reset()[0])
            sc.set_input(name, True)
            self.assertFalse(sc.tick()["may_move"])
            self.assertTrue(sc.reset()[0])

    def test_camera_zones(self):
        sc, cam = make()
        run(sc)
        cam.s["in_warning"] = True
        st = sc.tick()
        self.assertTrue(st["may_move"])
        self.assertEqual(st["speed_factor"], 0.25)            # slow down, keep going
        self.assertTrue(st["lamps"]["amber"])
        cam.s["in_danger"] = True
        st = sc.tick()
        self.assertFalse(st["may_move"])
        self.assertIn("PERSON", [f["code"] for f in st["latched"]])
        self.assertFalse(sc.reset()[0])                       # someone still there
        cam.s.update(in_danger=False, in_warning=False)
        self.assertTrue(sc.reset()[0])

    def test_required_camera_watchdog(self):
        sc, cam = make(require_camera=True)
        run(sc)
        cam.s["frame_age"] = 5.0
        self.assertIn("CAMERA", [f["code"] for f in sc.tick()["latched"]])

    def test_heartbeat_watchdog(self):
        sc, _ = make(heartbeat_timeout_s=0.2)
        run(sc)
        time.sleep(0.3)
        st = sc.status()                                      # no tick: the screen went quiet
        self.assertIn("HEARTBEAT", [f["code"] for f in st["latched"]])

    def test_fume_extraction(self):
        sc, _ = make()
        sc.set_input("extraction_on", False)
        sc.reset()
        sc.confirm_checklist()
        ok, why = sc.start()
        self.assertFalse(ok)
        self.assertTrue(any("extraction" in w for w in why))
        sc.set_input("extraction_on", True)
        run(sc)
        sc.set_input("extraction_on", False)
        self.assertIn("EXTRACTION", [f["code"] for f in sc.tick()["latched"]])

    def test_manual_mode_reduced_speed_hold_to_run(self):
        sc, _ = make()
        sc.set_mode("MANUAL")
        sc.set_input("gate_closed", False)                    # allowed in Manual (teaching inside)
        run(sc)
        st = sc.tick(enable=False)
        self.assertFalse(st["may_move"])                      # not holding enable
        st = sc.tick(enable=True)
        self.assertTrue(st["may_move"])
        self.assertAlmostEqual(st["speed_factor"], 0.25)      # 250 mm/s
        time.sleep(0.4)
        self.assertFalse(sc.status()["may_move"])             # let go -> stops

    def test_mode_change_stops_and_maintenance_isolates(self):
        sc, _ = make()
        run(sc)
        sc.set_mode("MANUAL")
        self.assertEqual(sc.tick()["state"], "NOT_RESET")
        with self.assertRaises(ValueError):
            sc.set_mode("MAINTENANCE")                        # must confirm lock-out
        sc.set_mode("MAINTENANCE", lockout_confirmed=True)
        st = sc.tick()
        self.assertEqual(st["state"], "ISOLATED")
        self.assertFalse(sc.reset()[0])
        self.assertFalse(sc.start()[0])
        sc.set_mode("AUTO")
        self.assertFalse(sc.tick()["checklist_ok"])           # checklist again after maintenance

    def test_event_log(self):
        sc, _ = make()
        run(sc)
        sc.press_estop("panel")
        texts = [e["text"] for e in sc.status()["events"]]
        self.assertTrue(any("E-STOP" in t for t in texts))
        self.assertTrue(any("START" in t for t in texts))


class Distance(unittest.TestCase):
    def test_iso_13855(self):
        # 30 mm curtain, 20 ms response, 600 ms machine stop: T = 0.62 s
        # 2000 x 0.62 + 128 = 1368 > 500, so K = 1600: 1600 x 0.62 + 128 = 1120 mm
        r = safety_distance({"resolution_mm": 30, "response_ms": 20, "machine_stop_ms": 600})
        self.assertEqual((r["S_mm"], r["K"], r["C_mm"]), (1120, 1600, 128))
        fast = safety_distance({"resolution_mm": 14, "response_ms": 10, "machine_stop_ms": 100})
        self.assertEqual((fast["S_mm"], fast["K"]), (220, 2000))


class Gpio(unittest.TestCase):
    def setUp(self):
        self.sc, _ = make()
        self.pins = {11: 0, 13: 0, 15: 0, 16: 1}            # all healthy, reset not pressed
        cfg = {"enabled": True, "estop_pin": 11, "gate_pin": 13, "curtain_pin": 15, "reset_pin": 16, "poll_hz": 50}
        self.io = GpioInputs(self.sc, cfg, backend=(lambda p: self.pins[p], "fake")).start()
        self.io.stop()                                       # drive it by hand
        self.io.poll_once()

    def test_wire_break_is_an_estop(self):
        run(self.sc)
        self.pins[11] = 1                                    # contact opened or wire cut
        self.io.poll_once()
        self.assertEqual(self.sc.tick()["state"], "ESTOP")

    def test_reset_button_and_gate_switch(self):
        self.pins[13] = 1
        self.io.poll_once()
        self.assertFalse(self.sc.tick()["inputs"]["gate_closed"])
        with self.assertRaises(ValueError):
            self.sc.set_input("gate_closed", True)           # screen can't override a real switch
        self.pins[13] = 0
        self.io.poll_once()
        self.pins[16] = 0                                    # press Reset
        self.io.poll_once()
        self.assertEqual(self.sc.tick()["state"], "READY")

    def test_gpio_failure_is_a_stop(self):
        run(self.sc)

        def broken(_):
            raise OSError("pin gone")
        self.io._read = broken
        self.io.poll_once()
        st = self.sc.tick()
        self.assertIn("GPIO", [f["code"] for f in st["latched"]])
        self.assertFalse(self.sc.reset()[0])


if __name__ == "__main__":
    unittest.main()
