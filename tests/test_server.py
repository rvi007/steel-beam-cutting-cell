"""The web server and its API, started for real on a free port."""
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from beamcell import plasma_presets, reports
from beamcell.server import Handler


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()                        # saved plasma settings and reports go here, not into the app's folders
        cls.folders = (plasma_presets.FOLDER, reports.FOLDER)
        plasma_presets.FOLDER, reports.FOLDER = cls.tmp + "/plasma", cls.tmp + "/reports"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        plasma_presets.FOLDER, reports.FOLDER = cls.folders
        shutil.rmtree(cls.tmp)

    def test_plasma_settings_saved_opened_and_used(self):
        start = self.get("/api/plasma/start?section=UB%20305x165x40&process=o2&grade=S275")
        self.assertEqual(start["name"], "UB 305x165x40 S275")
        start["web"]["speed_mm_min"] = 1200
        saved = self.post("/api/plasma/presets", start)
        names = [p["name"] for p in self.get("/api/plasma/presets")["presets"]]
        self.assertIn("UB 305x165x40 S275", names)
        self.assertEqual(self.get("/api/plasma/presets/UB%20305x165x40%20S275")["web"]["speed_mm_min"], 1200)
        job = {"section": "UB 305x165x40", "length": 2000, "cuts": [{"type": "cut", "x": 1000}], "check": False}
        plan = self.post("/api/manual/plan", dict(job, plasma=saved["name"]))
        self.assertEqual(plan["process"]["preset"], saved["name"])
        missing = self.post("/api/manual/plan", dict(job, plasma="no such settings"))
        self.assertIsNone(missing["process"]["preset"])
        self.assertIn("using the cut chart", missing["warnings"][0])
        self.post("/api/plasma/presets-delete/UB%20305x165x40%20S275", {})
        self.assertNotIn("UB 305x165x40 S275", [p["name"] for p in self.get("/api/plasma/presets")["presets"]])

    def test_start_measures_the_bar_and_refuses_a_wrong_one(self):
        from beamcell import sensors
        plan = self.post("/api/manual/plan", {"section": "UB 305x165x40", "length": 3000, "cuts": [{"type": "cut", "x": 2000}],
                                              "check": False})
        self.assertTrue(plan["bar_check"]["ok"])
        self.post("/api/safety/release", {"source": "screen"})
        self.post("/api/safety/clear-job", {})
        self.assertTrue(self.post("/api/safety/job", {"name": "bar check test", "plan_id": plan["plan_id"]})["ok"])
        self.post("/api/safety/checklist", {})
        self.post("/api/safety/reset", {})
        self.post("/api/safety/tick", {"client": "test"})
        try:
            self.post("/api/sensors/simulate-bar", {"mode": "short"})
            st = self.post("/api/safety/start", {})
            self.assertFalse(st["ok"])
            self.assertIn("short", st["why"][0])
            self.assertFalse(st["job"]["bar_check"]["ok"])
            self.post("/api/sensors/simulate-bar", {"mode": "ok"})          # the right bar loaded: measured again at Start
            self.post("/api/safety/tick", {"client": "test"})
            st = self.post("/api/safety/start", {})
            self.assertTrue(st["ok"], st["why"])
            self.assertTrue(st["job"]["bar_check"]["ok"])
        finally:
            sensors.SIM_BAR["mode"] = "ok"
            self.post("/api/safety/stop", {})
            self.post("/api/safety/finished", {})

    def test_reports_api(self):
        r = reports.record("ESTOP", "E-STOP pressed (test)", {"job": {"name": "t", "runs": 1}})
        reports.close_incident()
        listed = self.get("/api/reports")
        self.assertEqual(listed["settings"]["github_repo"], "rvi007/steel-beam-cutting-cell")
        self.assertIn(r["id"], [x["id"] for x in listed["reports"]])
        self.assertIn("E-STOP pressed (test)", self.get("/api/reports/" + r["id"])["text"])
        self.assertEqual(self.post("/api/reports/note", {"id": r["id"], "note": "hi"})["note"], "hi")
        self.assertTrue(self.post("/api/reports-sent/" + r["id"], {})["sent"])
        self.post("/api/reports-delete/" + r["id"], {})
        self.assertNotIn(r["id"], [x["id"] for x in self.get("/api/reports")["reports"]])

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            body = r.read()
            return json.loads(body) if r.headers.get_content_type() == "application/json" else body

    def post(self, path, body, raw=False):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return body.decode() if raw else json.loads(body)

    def test_pages_and_info(self):
        self.assertIn(b"Beam Cutting Cell", self.get("/"))
        self.assertIn(b"three", self.get("/js/scene.js"))
        info = self.get("/api/info")
        self.assertEqual(info["codes"]["hole_sizes"]["M20"]["normal"][0], 22)
        self.assertIn("cutter", info["machine"]["hands"])
        self.assertEqual(len(self.get("/api/sections")["UB"]), 107)

    def test_import_check_plan(self):
        names = self.get("/api/examples")
        self.assertIn("B1.nc1", names)
        b1 = self.get("/api/examples/B1.nc1")
        self.assertEqual(b1["part"]["mark"], "B1")
        with open("examples/nc1/T1_tekla_style.nc1") as fh:
            t1 = self.post("/api/nc1", {"filename": "T1.nc1", "text": fh.read()})
        self.assertEqual(t1["checks"], [])
        bars = self.post("/api/nest", {"parts": [b1["part"], t1["part"]], "stock_length": 12000})
        self.assertEqual(len(bars), 2)
        plan = self.post("/api/plan", {"parts": [b1["part"], t1["part"]], "stock_length": 12000, "bar": 1})
        self.assertEqual(plan["collisions"], 0)
        self.assertEqual(plan["bar"]["section"], "UB 305x165x40")
        self.assertTrue(plan["bar_check"]["ok"])
        self.assertTrue(all(c["process"]["speed_mm_min"] > 0 for c in plan["cuts"]))
        self.assertIn("ST", self.post("/api/nc1/export", {"part": t1["part"]}, raw=True))

    def test_manual_cut(self):
        job = {"section": "UB 305x165x40", "length": 4000,
               "cuts": [{"type": "cut", "x": 2000}, {"type": "hole", "face": "v", "x": 1000, "d": 22}]}
        ck = self.post("/api/manual/check", job)
        self.assertTrue(ck["ok"])
        self.assertEqual([p["keep"] for p in ck["pieces"]], [False, True])
        plan = self.post("/api/manual/plan", job)
        self.assertTrue(plan["manual"])
        self.assertEqual(plan["collisions"], 0)
        bad = self.post("/api/manual/plan", dict(job, cuts=[{"type": "cut", "x": 9000}]))
        self.assertIn("outside the bar", bad["error"])

    def test_safety_flow(self):
        st = self.post("/api/safety/tick", {"client": "test"})
        self.assertIn(st["state"], ("NOT_RESET", "READY", "ESTOP", "FAULT"))
        self.post("/api/safety/estop", {"source": "test"})
        self.assertEqual(self.get("/api/safety")["state"], "ESTOP")
        r = self.post("/api/safety/reset", {})
        self.assertFalse(r["ok"])                                  # still pressed
        self.post("/api/safety/release", {"source": "test"})
        self.assertTrue(self.post("/api/safety/reset", {})["ok"])
        self.assertFalse(self.post("/api/safety/start", {})["ok"])          # no job yet
        self.assertTrue(self.post("/api/safety/job", {"name": "test bar"})["ok"])
        self.post("/api/safety/checklist", {})
        self.post("/api/safety/tick", {"client": "test"})
        self.assertTrue(self.post("/api/safety/start", {})["ok"])
        self.assertFalse(self.post("/api/safety/clear-job", {})["ok"])     # not while running
        self.assertTrue(self.post("/api/safety/tick", {"client": "test"})["may_move"])
        self.post("/api/safety/input", {"name": "gate_closed", "value": False})
        self.assertEqual(self.get("/api/safety")["state"], "FAULT")
        self.post("/api/safety/input", {"name": "gate_closed", "value": True})
        self.post("/api/safety/finished", {"details": {"section": "UB 305x165x40", "parts": 3, "duration_s": 412}})
        self.post("/api/safety/finished", {})                      # again: no second history entry
        hist = [h for h in self.get("/api/history")["history"] if h["name"] == "test bar"]
        self.assertEqual(len(hist), 1)
        self.assertEqual((hist[0]["result"], hist[0]["parts"], hist[0]["section"]), ("finished", 3, "UB 305x165x40"))
        self.assertTrue(any("GATE" in p["text"].upper() for p in hist[0]["problems"]), hist[0]["problems"])   # the gate stop is in it
        self.assertNotIn("history", self.get("/api/jobs"))                 # the history file isn't a saved job
        with self.assertRaises(Exception):                                  # nor can a saved job overwrite it
            self.post("/api/jobs/history", {"parts": []})
        self.assertTrue(self.get("/api/history")["history"])
        left = self.post("/api/history-delete/" + hist[0]["id"], {})["history"]
        self.assertNotIn(hist[0]["id"], [h["id"] for h in left])
        st = self.get("/api/safety")
        self.assertEqual(st["job"]["state"], "finished")
        self.assertFalse(st["checklist_ok"])
        self.assertTrue(self.post("/api/safety/clear-job", {})["ok"])
        self.assertIsNone(self.get("/api/safety")["job"])
        self.post("/api/jobs/zz_test_job", {"parts": [], "stock_length": 6000})
        self.assertIn("zz_test_job", self.get("/api/jobs"))
        self.post("/api/jobs-delete/zz_test_job", {})
        self.assertNotIn("zz_test_job", self.get("/api/jobs"))
        self.assertIn("text", self.get("/api/situation"))
        sn = self.get("/api/sensors")
        self.assertGreaterEqual(len(sn["sensors"]), 15)
        self.assertIn("LOAD", [d["code"] for d in sn["decisions"]])
        self.assertTrue(self.post("/api/sensors/measure", {"section": "UB 305x165x40", "length": 6000})["ok"])
        self.assertEqual(self.post("/api/plasma/settings", {"feature": "hole", "thickness": 10, "d": 22})["thc"], "off")
        self.assertTrue(self.get("/api/plasma")["rows"])
        cfg = self.get("/api/config")
        self.assertEqual(cfg["problems"], [])
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/safety/mode", {"mode": "MAINTENANCE"})  # lock-out not confirmed
        self.assertEqual(e.exception.code, 400)

    def test_bad_requests(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/nc1", {"text": "not nc1"})
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/../beamcell/server.py")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
