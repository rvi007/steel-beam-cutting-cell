"""Parts: UK code rules, outlines, cut chains, nesting."""
import unittest

from beamcell import sections as S
from beamcell import uk_codes as UK
from beamcell.parts import Bar, Part, nest_all


def errors(part):
    return [c for c in part.check() if c["level"] == "error"]


class UKRules(unittest.TestCase):
    def test_hole_sizes_bs_en_1090_2(self):
        self.assertEqual(UK.hole_size("M12")[0], 13)
        self.assertEqual(UK.hole_size("M16")[0], 18)
        self.assertEqual(UK.hole_size("M20")[0], 22)
        self.assertEqual(UK.hole_size("M24")[0], 26)
        self.assertEqual(UK.hole_size("M27")[0], 30)
        self.assertEqual(UK.hole_size("M30")[0], 33)
        self.assertEqual(UK.hole_size("M20", "short slot"), (22, 28))

    def test_min_distances_ec3(self):
        m = UK.min_distances(22)
        self.assertAlmostEqual(m["e1"], 26.4)
        self.assertAlmostEqual(m["p1"], 48.4)

    def test_cope_to_clear_uses_blue_book(self):
        self.assertEqual(UK.cope_to_clear(S.get("UB 457x191x67")), (102.0, 24.0))


class PartChecks(unittest.TestCase):
    def good_beam(self):
        return Part("B1", "UB 305x165x40", 4000, holes=[
            {"face": "v", "x": 50, "y": 200, "d": 22}, {"face": "v", "x": 50, "y": 130, "d": 22},
            {"face": "o", "x": 2000, "y": 37.5, "d": 22}, {"face": "o", "x": 2000, "y": 127.5, "d": 22}],
            copes=[{"end": "start", "side": "top", "length": 102, "depth": 24, "radius": 10}])

    def test_good_part_passes(self):
        self.assertEqual(errors(self.good_beam()), [])

    def test_each_rule_is_caught(self):
        cases = {
            "flange root": {"face": "v", "x": 2000, "y": 15, "d": 22},
            "bottom-flange": {"face": "u", "x": 2000, "y": 40, "d": 22},
            "end distance": {"face": "v", "x": 20, "y": 150, "d": 22},        # 20 mm from the end (needs 26.4)
            "too small": {"face": "o", "x": 3000, "y": 37.5, "d": 8},
            "web root": {"face": "o", "x": 3000, "y": 75, "d": 22},
            "edge distance": {"face": "o", "x": 3000, "y": 10, "d": 22},
        }
        for words, hole in cases.items():
            p = self.good_beam()
            p.holes.append(hole)
            texts = " ".join(c["text"] for c in errors(p))
            self.assertIn(words.split()[0], texts, f"{words}: {texts}")

    def test_spacing(self):
        p = self.good_beam()
        p.holes.append({"face": "v", "x": 2000, "y": 150, "d": 22})
        p.holes.append({"face": "v", "x": 2030, "y": 150, "d": 22})
        self.assertTrue(any("apart" in c["text"] for c in errors(p)))

    def test_notch_rules(self):
        p = self.good_beam()
        p.copes[0]["depth"] = 12                     # less than tf + r = 19.1
        self.assertTrue(any("clear the flange" in c["text"] for c in errors(p)))
        p.copes[0].update(depth=24, radius=3)
        self.assertTrue(any("radius" in c["text"] for c in errors(p)))

    def test_hollow_sections_are_refused(self):
        p = Part("H", "SHS 100x100x5.0", 2000)
        self.assertTrue(any("hollow" in c["text"] for c in errors(p)))


class Shapes(unittest.TestCase):
    def test_notch_outline_and_chains(self):
        p = Part("B", "UB 305x165x40", 4000, copes=[{"end": "start", "side": "top", "length": 102, "depth": 24, "radius": 10}])
        o = p.face_outline("o")
        self.assertAlmostEqual(min(x for x, _ in o), 102)          # top flange starts after the notch
        web = p.chains("v")
        self.assertEqual(sorted(c["end"] for c in web), ["end", "start"])
        self.assertFalse(p.end_is_square("start"))
        self.assertTrue(p.end_is_square("end"))

    def test_mitre(self):
        p = Part("B", "UB 305x165x40", 4000, mitres={"end": {"web": 10}})
        xs = [x for x, _ in p.face_outline("u")]
        self.assertLess(max(xs), 4000 - 50)                         # bottom flange shorter


class Nesting(unittest.TestCase):
    def test_trim_shared_cut_and_gap(self):
        plain = Part("A", "UB 305x165x40", 3000, qty=2)
        notched = Part("B", "UB 305x165x40", 2000, copes=[{"end": "start", "side": "top", "length": 102, "depth": 24}])
        bar = Bar("UB 305x165x40", 12000, [plain, notched])
        pl = bar.placements
        self.assertEqual(pl[0]["x0"], UK.TRIM)
        self.assertTrue(pl[1]["start_shared"])                     # square to square: one cut
        self.assertEqual(pl[2]["x0"] - pl[1]["x1"], UK.GAP)        # notch needs its own cut
        self.assertEqual(bar.remnant[1], 12000)

    def test_more_bars_when_full(self):
        bars = nest_all([Part("A", "UB 305x165x40", 5000, qty=5)], 12000)
        self.assertEqual([len(b.placements) for b in bars], [2, 2, 1])


if __name__ == "__main__":
    unittest.main()
