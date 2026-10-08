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
        # crane-lift notes and plasma capacity limits (e.g. a 125 mm flange is beyond plasma) are not safety problems
        warnings = [w for w in plan.warnings if "crane" not in w and not w.startswith("Plasma - ")]
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


class Gravity(unittest.TestCase):
    """Nothing floats: every piece ends up resting on the rollers, the outfeed table or the scrap tray."""

    def test_every_piece_rests_on_something(self):
        from beamcell.machine import BED_Z, OUTFEED_DECK, SCRAP_TRAY_Z, fall_time, supported_on_rollers
        parts = []
        for f in sorted(glob.glob(os.path.join(EXAMPLES, "*.nc1"))):
            with open(f) as fh:
                parts.append(nc1.read(fh.read(), f)[0])
        for stock in (12000, 6000):
            for bar in nest_all(parts, stock):
                plan = Plan(bar).build()
                carried = {c["placement"] for c in plan.carries}
                for c in plan.carries:                   # put down ON the table, not above or in it
                    pl = bar.placements[c["placement"]]
                    self.assertAlmostEqual(c["offset"][2], 0.0, places=6)
                    y = -0.5 + c["offset"][1]
                    self.assertTrue(OUTFEED_DECK[2] < y < OUTFEED_DECK[3])
                    self.assertTrue(OUTFEED_DECK[0] <= pl["x0"] / 1000 and pl["x1"] / 1000 <= OUTFEED_DECK[1])
                for k, pl in enumerate(bar.placements):  # parts not carried stay on two rollers
                    if k not in carried:
                        self.assertTrue(supported_on_rollers(pl["x0"] / 1000, pl["x1"] / 1000), bar.section_title)
                for d in plan.drops:                     # offcuts fall for the right time into the tray
                    self.assertAlmostEqual(d["t_land"] - d["t"], fall_time(BED_Z - SCRAP_TRAY_Z), places=6)
                    self.assertTrue(d["remnant"] or d["x1"] - d["x0"] <= 25)
                rem = bar.remnant
                if rem:
                    dropped = any(d["remnant"] for d in plan.drops)
                    self.assertEqual(dropped, not supported_on_rollers(rem[0] / 1000, rem[1] / 1000))

    def test_supported_on_rollers(self):
        from beamcell.machine import supported_on_rollers
        self.assertTrue(supported_on_rollers(0.0, 12.0))
        self.assertTrue(supported_on_rollers(4.4, 5.6))      # rollers at 4.5 and 5.5
        self.assertFalse(supported_on_rollers(4.6, 5.4))     # no roller under it
        self.assertFalse(supported_on_rollers(4.4, 4.9))     # one roller only: it tips off


class TwentyMetreMachine(unittest.TestCase):
    """The same software drives the 12 m and the 20 m cell."""

    def tearDown(self):
        from beamcell import machine
        machine.set_length(12)

    def test_a_20_m_bar_plans_without_collisions(self):
        from beamcell import collisions, machine, manual
        machine.set_length(20)
        self.assertEqual(machine.X_LIMITS[1], 21.3)
        self.assertEqual(len(machine.ROLLER_X), 20)
        bar, _ = manual.build("UB 305x165x40", 20000, [{"type": "hole", "face": "v", "x": 18500, "d": 22}, {"type": "cut", "x": 19000}])
        plan = Plan(bar).build()
        self.assertGreater(plan.scan["passes"][0]["t1"], plan.scan["passes"][0]["t0"] + 25)   # it measures all 20 m
        self.assertEqual(collisions.check_plan(plan, step=0.4), [])
        self.assertGreaterEqual(plan.min_gap(), 1.0)

    def test_the_12_m_machine_refuses_a_20_m_bar(self):
        from beamcell import manual
        bar, problems = manual.build("UB 305x165x40", 20000, [{"type": "cut", "x": 1000}])
        self.assertIsNone(bar)
        self.assertIn("12 m machine", problems[0]["text"])
