"""Planning both hands: every example bar, plus a spread of sections, must be safe."""
import glob
import os
import unittest

from beamcell import nc1
from beamcell import sections as S
from beamcell.collisions import check_plan
from beamcell.machine import MIN_GAP
from beamcell.parts import Bar, inside, nest_all
from beamcell.planner import Plan
from tests.sweep_sections import typical_part

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "nc1")


class Planner(unittest.TestCase):
    def assertSafe(self, plan, label):
        hits = check_plan(plan, step=0.4)
        warnings = [w for w in plan.warnings if "crane" not in w]
        self.assertEqual(hits, [], f"{label}: collisions")
        self.assertEqual(warnings, [], f"{label}: warnings")
        self.assertGreaterEqual(plan.min_gap(), MIN_GAP - 1e-9, label)

    def test_example_bars(self):
        parts = []
        for f in sorted(glob.glob(os.path.join(EXAMPLES, "*.nc1"))):
            with open(f) as fh:
                parts.append(nc1.read(fh.read(), f)[0])
        bars = nest_all(parts, 12000)
        self.assertGreaterEqual(len(bars), 5)
        for bar in bars:
            plan = Plan(bar).build()
            self.assertSafe(plan, bar.section_title)
            ops = plan.to_json()["ops"]
            n_holes = sum(len(bar.parts[pl["part"]].holes) for pl in bar.placements)
            self.assertEqual(sum(1 for o in ops if o["kind"] in ("hole", "slot")), n_holes, bar.section_title)
            carried = {c["placement"] for c in plan.carries}
            self.assertEqual(carried, set(range(len(bar.placements))), f"{bar.section_title}: every part carried")

    def test_spread_of_sections(self):
        """Every 9th cuttable section, smallest to biggest (tests/sweep_sections.py does them all)."""
        cuttable = [s for rows in S.library().values() for s in rows if s["kind"] in S.CUTTABLE]
        for s in cuttable[::9] + [cuttable[0], cuttable[-1]]:
            plan = Plan(Bar(s["title"], 6000, [typical_part(s)])).build()
            self.assertSafe(plan, s["title"])

    def test_plan_json(self):
        bar = Bar("UB 305x165x40", 6000, [typical_part(S.get("UB 305x165x40"))])
        d = Plan(bar).build().to_json()
        for key in ("summary", "tracks", "cuts", "ops", "carries", "drops", "steps"):
            self.assertIn(key, d)
        self.assertEqual(len(d["tracks"]["cutter"]["t"]), len(d["tracks"]["cutter"]["q"]))


if __name__ == "__main__":
    unittest.main()


class CutOrder(unittest.TestCase):
    def test_examples_web_holes_centred(self):
        """Web bolt groups in the examples sit on the middle of the web that's left (not random)."""
        for name in ("B1", "B2", "G1", "T1_tekla_style"):
            with open(os.path.join(EXAMPLES, name + ".nc1")) as fh:
                part = nc1.read(fh.read(), name)[0]
            s = part.sec
            groups = {}
            for h in part.holes:
                self.assertEqual(h["face"], "v", f"{name}: only web holes")
                groups.setdefault(h["x"], []).append(h["y"])
            web = part.face_outline("v")
            for x, ys in groups.items():
                lo = s["tf"] + s["r"]
                top = max(y / 2 for y in range(0, int(s["h"] * 2)) if inside(web, x, y / 2))   # under any notch
                hi = min(top, s["h"] - s["tf"]) - (s["r"] if top >= s["h"] - s["tf"] - 1 else 0)
                self.assertAlmostEqual(sum(ys) / len(ys), (lo + hi) / 2, delta=1.0, msg=f"{name} group at x={x}")

    def test_cut_in_order_along_the_bar(self):
        """Start cut first, then holes going along the bar (never jumping back), then the cut-off."""
        from beamcell.planner import bar_operations
        parts = []
        for f in ("B1", "G1", "C1"):
            with open(os.path.join(EXAMPLES, f + ".nc1")) as fh:
                parts.append(nc1.read(fh.read(), f)[0])
        for bar in nest_all(parts, 12000):
            for ops in bar_operations(bar)[0]:
                kinds = [o["kind"] for o in ops]
                if "start" in kinds:
                    self.assertEqual(kinds[0], "start")
                if "end" in kinds:
                    self.assertEqual(kinds[-1], "end")
                xs = [float(o["passes"][0][0][:, 0].mean()) for o in ops if o["kind"] not in ("start", "end")]
                for a, b in zip(xs, xs[1:]):
                    self.assertGreater(b, a - 0.16, "went back along the bar")
