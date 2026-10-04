"""
Writes the example NC1 files in examples/nc1/ - realistic UK details, so the demo cuts what a
real drawing would ask for:

    B1   UB 305x165x40 x 5200  secondary beam: top notch both ends to clear a UB 457 main beam,
                               3 x M20 fin-plate holes each end, centred on the web left below the notch
    B2   UB 305x165x40 x 1650  short trimmer: 3 x M20 each end, centred on the web depth
    G1   UB 457x191x67 x 6000  main beam: 4 x M20 each end and a 3 x M20 fin plate at mid-span
                               (where B1 connects), all centred on the web depth
    C1   UC 203x203x46 x 3600  column: 3 pairs of M20 in the top flange at 140 mm cross-centres
    P1   PFC 200x90x30 x 2400  rail: M16 holes every 600 mm on the web centre line
    A1   EA 90x90x8 x 1100     bracing angle: M16 pairs at each end on the 50 mm back mark

    python3 tools/make_examples.py      (T1_tekla_style.nc1 is hand-written and not touched)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beamcell import nc1                                  # noqa: E402
from beamcell import sections as S                        # noqa: E402
from beamcell.parts import Part                           # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "nc1")


def web_group(x, n, pitch, centre, d=22.0):
    """n holes in a vertical line on the web, centred on height `centre` (mm from the underside)."""
    return [{"face": "v", "x": x, "y": round(centre + (i - (n - 1) / 2) * pitch, 1), "d": d} for i in reversed(range(n))]


def main():
    parts = []
    # B1: notched both ends; the bolt group is centred on the web that is left under the notch
    s = S.get("UB 305x165x40")
    sup = S.get("UB 457x191x67")
    N, n = 105.0, round(sup["tf"] + sup["r"] + 1)
    clear_lo, clear_hi = s["tf"] + s["r"], s["h"] - n
    mid = (clear_lo + clear_hi) / 2
    parts.append(Part("B1", s["title"], 5200, 2, holes=web_group(50, 3, 70, mid) + web_group(5150, 3, 70, mid),
                      copes=[{"end": e, "side": "top", "length": N, "depth": n, "radius": 10} for e in ("start", "end")]))
    parts.append(Part("B2", s["title"], 1650, 1, holes=web_group(40, 3, 70, s["h"] / 2) + web_group(1610, 3, 70, s["h"] / 2)))
    g = S.get("UB 457x191x67")
    parts.append(Part("G1", g["title"], 6000, 1, holes=web_group(45, 4, 70, g["h"] / 2) + web_group(3000, 3, 70, g["h"] / 2)
                      + web_group(5955, 4, 70, g["h"] / 2)))
    c = S.get("UC 203x203x46")
    cc = 140.0
    parts.append(Part("C1", c["title"], 3600, 1, holes=[{"face": "o", "x": x, "y": round(c["b"] / 2 + k * cc / 2, 1), "d": 22.0}
                                                         for x in (3300, 3370, 3440) for k in (-1, 1)]))
    p = S.get("PFC 200x90x30")
    parts.append(Part("P1", p["title"], 2400, 2, holes=[{"face": "v", "x": x, "y": p["h"] / 2, "d": 18.0} for x in (300, 900, 1500, 2100)]))
    a = S.get("EA 90x90x8.0")
    parts.append(Part("A1", a["title"], 1100, 4, holes=[{"face": "v", "x": x, "y": 50.0, "d": 18.0} for x in (40, 110, 990, 1060)]
                      + [{"face": "u", "x": x, "y": 50.0, "d": 18.0} for x in (40, 1060)]))
    for part in parts:
        bad = [i for i in part.check() if i["level"] == "error"]
        if bad:
            raise SystemExit(f"{part.mark}: {bad}")
        with open(os.path.join(OUT, part.mark + ".nc1"), "w") as fh:
            fh.write(nc1.write(part))
        print(part.mark, part.section_title, len(part.holes), "holes")


if __name__ == "__main__":
    main()
