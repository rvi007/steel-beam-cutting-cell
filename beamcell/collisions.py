"""
Collision checks for a plan: do the arms or tools ever go through the steel?

Each arm is a chain of line segments between its joints, sampled every 2 cm. A point is a
hit if it's inside one of the steel's solid boxes or below the bed. The steel is split into
boxes plate by plate (flanges, web, legs), following each plate's real outline - so notches
and end cuts count. The last few mm of the torch are skipped: it's meant to be close.
"""
import numpy as np

from beamcell import sections as S
from beamcell.machine import BEAM_Y, BED_Z
from beamcell.parts import x_intervals_inside

TIP_SKIP = 0.012
MARGIN = 0.002


def plate_boxes(part, x0):
    """Solid boxes (x0, x1, y0, y1, z0, z1) in metres for a part lying at x0 mm on the bar."""
    s = part.sec
    boxes = []
    for pl in S.plates(s):
        face = pl["face"]
        poly = part.face_outline(face)
        swapped = [(y, x) for x, y in poly]
        xs = sorted({round(p[0], 3) for p in poly})
        for xa, xb in zip(xs[:-1], xs[1:]):
            if xb - xa < 1.0:
                continue
            for ya, yb in x_intervals_inside(swapped, (xa + xb) / 2):
                if pl["flat"]:
                    ua, ub = max(S.face_to_section(s, face, yb), pl["u0"]), min(S.face_to_section(s, face, ya), pl["u1"])
                    va, vb = pl["v0"], pl["v1"]
                else:
                    ua, ub = pl["u0"], pl["u1"]
                    va, vb = max(ya, pl["v0"]), min(yb, pl["v1"])
                if ua < ub and va < vb:
                    boxes.append(((x0 + xa) / 1000, (x0 + xb) / 1000, BEAM_Y + ua / 1000, BEAM_Y + ub / 1000,
                                  BED_Z + va / 1000, BED_Z + vb / 1000))
    return boxes


def stock_boxes(section, x0, x1):
    """Plain pieces of stock (offcuts, remnant) as boxes."""
    return [((x0) / 1000, x1 / 1000, BEAM_Y + p["u0"] / 1000, BEAM_Y + p["u1"] / 1000,
             BED_Z + p["v0"] / 1000, BED_Z + p["v1"] / 1000) for p in S.plates(section)]


def arm_points(hand, g, q, spacing=0.02):
    pts = np.array([F[:3, 3] for F in hand.world_frames(g, q)])
    out = []
    for i, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
        L = np.linalg.norm(b - a)
        if i == len(pts) - 2:                     # tool: stop short of the tip
            if L <= TIP_SKIP:
                continue
            b = a + (b - a) * (L - TIP_SKIP) / L
            L -= TIP_SKIP
        n = max(2, int(L / spacing) + 1)
        out.append(a + np.linspace(0, 1, n)[:, None] * (b - a))
    return np.vstack(out)


def hits(points, boxes):
    found = set()
    for k, (x0, x1, y0, y1, z0, z1) in enumerate(boxes):
        inside = ((points[:, 0] > x0 + MARGIN) & (points[:, 0] < x1 - MARGIN) &
                  (points[:, 1] > y0 + MARGIN) & (points[:, 1] < y1 - MARGIN) &
                  (points[:, 2] > z0 + MARGIN) & (points[:, 2] < z1 - MARGIN))
        if inside.any():
            found.add(k)
    return found


def check_plan(plan, step=0.3):
    """List of problems: (time, hand name, what was hit)."""
    bar = plan.bar
    section = bar.parts[0].sec if bar.parts else None
    fixed = []
    if bar.remnant:
        fixed += stock_boxes(section, *bar.remnant)
    part_boxes = [plate_boxes(bar.parts[pl["part"]], pl["x0"]) for pl in bar.placements]
    problems = []
    for t in np.arange(0, plan.duration, step):
        boxes = list(fixed)
        for k, pb in enumerate(part_boxes):
            off = plan.part_offset(k, t)
            boxes += [(b[0] + off[0], b[1] + off[0], b[2] + off[1], b[3] + off[1], b[4] + off[2], b[5] + off[2])
                      for b in pb]
        for drop in plan.drops:                       # offcuts are still there until they drop
            if t < drop["t"]:
                boxes += stock_boxes(section, drop["x0"], drop["x1"])
        for track in (plan.tc, plan.th):
            g, q = track.at(t)
            pts = arm_points(track.hand, g, q)
            if track is plan.th:      # the magnet touches the part it holds: skip its last 3 cm
                pts = pts[:-2]
            if np.any(pts[:, 2] < BED_Z - 0.01):
                problems.append((round(t, 1), track.hand.name, "below the bed"))
            for k in hits(pts, boxes):
                problems.append((round(t, 1), track.hand.name, f"steel box {k}"))
    return problems
