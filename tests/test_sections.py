"""UK section library: sizes, exact outlines, and name matching."""
import unittest

from beamcell import sections as S


def area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                     for i in range(len(poly)))


class Sections(unittest.TestCase):
    def test_every_family_is_there(self):
        lib = S.library()
        want = {"UB": 107, "UC": 46, "UBP": 17, "PFC": 16, "EA": 42, "UA": 39,
                "SHS-HF": 123, "RHS-HF": 161, "CHS-HF": 103, "SHS-CF": 96, "RHS-CF": 137, "CHS-CF": 106}
        self.assertEqual({k: len(v) for k, v in lib.items()}, want)

    def test_outline_area_matches_table_mass(self):
        """Outline area x 7850 kg/m3 must give the published mass: proves the radii are right."""
        worst = (0, "")
        for rows in S.library().values():
            for s in rows:
                outer, holes = S.outline(s)
                a = area(outer) - sum(abs(area(h)) for h in holes)
                mass = a * 7.85e-3
                err = abs(mass - s["m"]) / s["m"]
                worst = max(worst, (err, s["title"]))
        self.assertLess(worst[0], 0.03, f"worst: {worst}")

    def test_known_sizes(self):
        s = S.get("UB 457x191x67")
        self.assertEqual((s["h"], s["b"], s["tw"], s["tf"], s["r"], s["N"], s["n"]), (453.4, 189.9, 8.5, 12.7, 10.2, 102, 24))
        a = S.get("EA 100x100x10.0")
        self.assertEqual((a["t"], a["r1"], a["r2"]), (10.0, 12.0, 6.0))

    def test_names_from_other_software(self):
        for text, title in [("UB457*191*67", "UB 457x191x67"), ("UKB457x191x67", "UB 457x191x67"),
                            ("457x191x67UB", "UB 457x191x67"), ("PFC200*90*30", "PFC 200x90x30"),
                            ("UC203*203*46", "UC 203x203x46"), ("L100*100*10", "EA 100x100x10.0"),
                            ("L150X90X10", "UA 150x90x10"), ("SHS100*100*5", "SHS 100x100x5.0")]:
            self.assertEqual(S.find(text)["title"], title, text)
        self.assertIsNone(S.find("W12x26"))

    def test_plates_cover_the_section(self):
        for title in ("UB 305x165x40", "PFC 200x90x30", "UA 150x90x10"):
            s = S.get(title)
            for p in S.plates(s):
                self.assertLess(p["u0"], p["u1"])
                self.assertLess(p["v0"], p["v1"])
                self.assertLessEqual(p["v1"], s["h"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
