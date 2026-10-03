"""Plan a typical part on EVERY cuttable UK section and check for collisions.
Slow (several minutes) - run by hand: python3 tests/sweep_sections.py [--every N]"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: E402
from beamcell import sections as S                           # noqa: E402
from beamcell.collisions import check_plan                    # noqa: E402
from beamcell.parts import Bar, Part                          # noqa: E402
from beamcell.planner import Plan                             # noqa: E402


def typical_part(s):
    """A 2 m part with a web hole, flange holes where they fit, and a notch on beams."""
    d = max(18.0, round(max(s["tw"], s["tf"]) + 2))
    holes = []
    k = s["kind"]
    if k in ("I", "U"):
        holes.append({"face": "v", "x": 1000, "y": s["h"] / 2, "d": d})
        if k == "I":
            u = (s["tw"] / 2 + s["r"] + s["b"] / 2) / 2
            if s["b"] / 2 - u >= 1.2 * d and u - d / 2 >= s["tw"] / 2 + s["r"]:
                holes += [{"face": "o", "x": 600, "y": S.section_to_face(s, "o", sg * u), "d": d} for sg in (1, -1)]
    else:
        holes.append({"face": "v", "x": 1000, "y": (s["t"] + s["r1"] + s["h"]) / 2, "d": d})
        holes.append({"face": "u", "x": 1400, "y": (s["t"] + s["r1"] + s["b"]) / 2, "d": d})
    p = Part("T", s["title"], 2000, 1, holes=holes)
    if k == "I" and s["h"] >= 200:
        n = s["tf"] + s["r"] + 10
        p.copes = [{"end": "start", "side": "top", "length": 100, "depth": n, "radius": 10}]
    p.holes = [h for i, h in enumerate(p.holes)
               if not any(x["level"] == "error" and x["item"] == f"hole {i + 1}" for x in p.check())]
    return p


def main():
    every = int(sys.argv[sys.argv.index("--every") + 1]) if "--every" in sys.argv else 1
    bad = 0
    t0 = time.time()
    count = 0
    for fam, rows in S.library().items():
        for s in rows[::every]:
            if s["kind"] not in S.CUTTABLE:
                continue
            count += 1
            part = typical_part(s)
            errors = [x for x in part.check() if x["level"] == "error"]
            plan = Plan(Bar(s["title"], 6000, [part])).build()
            hits = check_plan(plan, step=0.4)
            warn = [w for w in plan.warnings if "too heavy" not in w and "crane" not in w]
            if errors or hits or warn or plan.min_gap() < 1.0:
                bad += 1
                print(f"FAIL {s['title']}: errors {errors[:1]} hits {len(hits)} {hits[:2]} warnings {warn[:2]}", flush=True)
    print(f"{count} sections, {bad} with problems, {time.time() - t0:.0f} s")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
