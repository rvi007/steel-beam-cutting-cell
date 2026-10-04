"""Manual cutting: the operator's holes, cuts and notches become pieces, checks and a safe plan."""
import unittest

from beamcell import manual
from beamcell.collisions import check_plan
from beamcell.planner import Plan


def plan_of(section, length, cuts):
    bar, problems = manual.build(section, length, cuts)
    return bar, problems, Plan(bar).build()


class Manual(unittest.TestCase):
    def test_pieces_and_what_happens_to_them(self):
        bar, problems, plan = plan_of("UB 305x165x40", 6000, [
            {"type": "cut", "x": 10},                                   # square the mill end: a 10 mm offcut
            {"type": "hole", "face": "v", "x": 300, "d": 22},            # y left out: centre of the web
            {"type": "cut", "x": 2000},
            {"type": "cut", "x": 4000, "angle": 30},
        ])
        self.assertEqual([p for p in problems if p["level"] == "error"], [])
        pls = bar.placements
        self.assertEqual(len(pls), 4)
        self.assertTrue(pls[0]["scrap"])                                 # falls into the tray
        self.assertTrue(pls[-1]["keep"])                                 # the rest stays on the rollers
        self.assertEqual(bar.parts[1].holes[0]["y"], 303.4 / 2)
        self.assertAlmostEqual(bar.parts[1].holes[0]["x"], 290.0)
        self.assertEqual(check_plan(plan, step=0.4), [])
        self.assertEqual(plan.warnings, [])
        self.assertEqual(len(plan.carries), 2)                           # pieces 2 and 3 to the outfeed table
        self.assertEqual(len(plan.drops), 1)
        # the mitred cut is one straight line shared by both pieces: same angle, opposite sign
        self.assertEqual(bar.parts[2].mitres["end"]["web"], 30)
        self.assertEqual(bar.parts[3].mitres["start"]["web"], -30)
        self.assertAlmostEqual(pls[2]["x1"] - pls[3]["x0"], 2 * 0.57735 * 303.4 / 2, places=1)

    def test_notch_gets_its_own_start_cut(self):
        bar, problems, plan = plan_of("UB 305x165x40", 4000, [
            {"type": "cut", "x": 2000},
            {"type": "notch", "x": 2000, "on": "after", "side": "top", "length": 100, "depth": 25},
        ])
        self.assertEqual([p for p in problems if p["level"] == "error"], [])
        self.assertFalse(bar.placements[1]["start_shared"])
        labels = [o["label"] for o in plan.ops]
        self.assertIn("start cut", labels)
        self.assertEqual(check_plan(plan, step=0.4), [])

    def test_rules_still_apply(self):
        _, problems = manual.build("UB 305x165x40", 4000, [
            {"type": "hole", "face": "v", "x": 1000, "y": 15, "d": 22},    # in the flange root
            {"type": "hole", "face": "v", "x": 1030, "d": 22},             # too close to the next one
            {"type": "hole", "face": "v", "x": 1060, "d": 22},
        ])
        text = " ".join(p["item"] + " " + p["text"] for p in problems)
        self.assertIn("cut 1 (hole)", text)
        self.assertIn("root", text)
        self.assertIn("apart", text)
        _, problems = manual.build("UB 305x165x40", 4000, [{"type": "notch", "x": 1500, "length": 100, "depth": 25}])
        self.assertIn("add the cut first", problems[0]["text"])
        _, problems = manual.build("SHS-HF 100x100x5.0", 4000, [])
        self.assertEqual(problems[0]["item"], "section")
        _, problems = manual.build("UB 305x165x40", 4000, [{"type": "cut", "x": 5000}])
        self.assertIn("outside the bar", problems[0]["text"])


if __name__ == "__main__":
    unittest.main()
