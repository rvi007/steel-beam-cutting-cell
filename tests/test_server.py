"""The web server and its API, started for real on a free port."""
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from beamcell.server import Handler


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

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
        self.assertIn("ST", self.post("/api/nc1/export", {"part": t1["part"]}, raw=True))

    def test_bad_requests(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/nc1", {"text": "not nc1"})
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/../beamcell/server.py")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
