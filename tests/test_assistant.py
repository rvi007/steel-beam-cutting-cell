"""'What's happening' sentences (no AI) and the optional advisor's request (with a fake client)."""
import copy
import unittest
from types import SimpleNamespace

from beamcell import assistant
from beamcell.config import CONFIG, DEFAULTS
from beamcell.safety import SafetyController


def status(**kw):
    sc = SafetyController(config=copy.deepcopy(DEFAULTS["safety"]), log_path="")
    for k, v in kw.items():
        getattr(sc, k)(*v) if isinstance(v, tuple) else getattr(sc, k)(v)
    return sc.tick()


class Situation(unittest.TestCase):
    def test_estop_sentence(self):
        st = status(press_estop="panel")
        text = assistant.situation(st)["text"]
        self.assertIn("EMERGENCY STOP", text)
        self.assertIn("release the E-stop", text)

    def test_running_with_playback_and_camera(self):
        sc = SafetyController(config=copy.deepcopy(DEFAULTS["safety"]), log_path="")
        sc.reset()
        sc.confirm_checklist()
        sc.start()
        st = sc.tick(playback={"cutter": "B1: hole 3 (face v)", "handler": "holding B1", "bar": "UB 305x165x40 bar 1 of 2", "progress": 40})
        text = assistant.situation(st, sc.playback, {"enabled": True, "people": 1, "in_warning": True})["text"]
        for words in ("Running in Auto", "Cutter: B1: hole 3", "Handler: holding B1", "40% done", "warning zone"):
            self.assertIn(words, text)


class FakeClient:
    def __init__(self, reply="Gate opened, close it and press Reset.", stop="end_turn"):
        self.calls = []
        msg = SimpleNamespace(stop_reason=stop, model="claude-opus-5-5", content=[SimpleNamespace(type="text", text=reply)])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (self.calls.append(kw), msg)[1]))


class Advisor(unittest.TestCase):
    def test_request_shape(self):
        fake = FakeClient()
        old = dict(CONFIG["assistant"])
        CONFIG["assistant"].update(enabled=True, send_camera=True)
        try:
            r = assistant.ask("why did it stop?", {"state": "FAULT"}, jpeg=b"\xff\xd8fake", client=fake)
        finally:
            CONFIG["assistant"].clear()
            CONFIG["assistant"].update(old)
        self.assertEqual(r["answer"], "Gate opened, close it and press Reset.")
        kw = fake.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertEqual(kw["output_config"], {"effort": "low"})
        content = kw["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "image")
        self.assertIn("why did it stop?", content[1]["text"])
        self.assertIn("Never tell anyone to bypass", kw["system"])

    def test_refusal_is_reported(self):
        r = assistant.ask("q", {}, client=FakeClient(stop="refusal"))
        self.assertIn("declined", r["error"])

    def test_off_by_default(self):
        ok, why = assistant.available()
        self.assertFalse(ok)
        self.assertIn("switched off", why)
        self.assertIn("error", assistant.ask("hello", {}))


if __name__ == "__main__":
    unittest.main()
