"""DSTV NC1 files: the examples, round trips, and messy real-world formatting."""
import glob
import os
import unittest

from beamcell import nc1
from beamcell.parts import Part

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "nc1")


class NC1(unittest.TestCase):
    def test_examples_read_clean(self):
        files = sorted(glob.glob(os.path.join(EXAMPLES, "*.nc1")))
        self.assertGreaterEqual(len(files), 7)
        for f in files:
            with open(f) as fh:
                part, report = nc1.read(fh.read(), os.path.basename(f))
            self.assertEqual([c for c in part.check() if c["level"] == "error"], [], f)
            self.assertTrue(report)

    def test_round_trip(self):
        p = Part("X1", "UB 305x165x40", 4200, 3, holes=[{"face": "v", "x": 50, "y": 200, "d": 22},
                                                       {"face": "o", "x": 900, "y": 37.5, "d": 18, "slot": 40, "angle": 0}],
                 copes=[{"end": "end", "side": "bottom", "length": 90, "depth": 30, "radius": 10}],
                 mitres={"start": {"web": 5}})
        q, _ = nc1.read(nc1.write(p))
        self.assertEqual((q.mark, q.section_title, q.length, q.qty), ("X1", "UB 305x165x40", 4200, 3))
        self.assertEqual(len(q.holes), 2)
        self.assertEqual(q.holes[1]["slot"], 40)
        for face in p.faces():
            a = [tuple(round(c, 2) for c in pt) for pt in p.face_outline(face)]
            b = [tuple(round(c, 2) for c in pt) for pt in q.face_outline(face)]
            self.assertEqual(a, b, face)

    def test_messy_file(self):
        text = """ST
** hand written, odd spacing
  J1
  D1
  1
  M7
  S275JR
  2
  PFC200*90*30
  U
  1500.00,1502.00
  200
  90
  14
  7
  12
  29.7
  0.6
  0
  0
  0
  0
BO
  v100.00s 100.00 18.00 0
  v1400.00 100.00 18.00 0
SI
  v 50 50 0 10r M7
KO
  v 10 10 0
EN
"""
        part, report = nc1.read(text, "m7.nc1")
        self.assertEqual((part.mark, part.section_title, part.length, part.qty, part.grade),
                         ("M7", "PFC 200x90x30", 1500.0, 2, "S275JR"))
        self.assertEqual([(h["face"], h["x"], h["y"], h["d"]) for h in part.holes],
                         [("v", 100.0, 100.0, 18.0), ("v", 1400.0, 100.0, 18.0)])
        self.assertTrue(any("hard stamping" in r for r in report))

    def test_unknown_profile_uses_file_sizes(self):
        text = "ST\n  O\n  D\n  1\n  Z1\n  S355J2\n  1\n  HE300A\n  I\n  2000\n  290\n  300\n  14\n  8.5\n  27\n  88.3\n" + "  0\n" * 6 + "EN\n"
        part, report = nc1.read(text)
        self.assertEqual(part.sec["h"], 290)
        self.assertTrue(any("not in the UK library" in r for r in report))

    def test_not_an_nc1(self):
        with self.assertRaises(ValueError):
            nc1.read("hello world")


if __name__ == "__main__":
    unittest.main()
