"""
Collision checks for a plan: do the arms or tools ever go through the steel?

Each arm is treated as a chain of line segments between its joints (like the
drawing), sampled every 2 cm. A point counts as a hit if it is inside one of
the beam's solid boxes (top flange, web, bottom flange) or below the bed.
The last few mm of the tool are skipped - the torch is meant to be close.
"""
import numpy as np

from gantry.machine import BED_Z

TIP_SKIP = 0.012      # ignore this much of the tool tip (torch standoff is 3 mm)
MARGIN = 0.002


def arm_points(hand, g, q, spacing=0.02):
    frames = hand.world_frames(g, q)
    pts = np.array([F[:3, 3] for F in frames])
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
    """Indices of boxes any point is inside."""
    found = set()
    for k, (x0, x1, y0, y1, z0, z1) in enumerate(boxes):
        inside = ((points[:, 0] > x0 + MARGIN) & (points[:, 0] < x1 - MARGIN) &
                  (points[:, 1] > y0 + MARGIN) & (points[:, 1] < y1 - MARGIN) &
                  (points[:, 2] > z0 + MARGIN) & (points[:, 2] < z1 - MARGIN))
        if inside.any():
            found.add(k)
    return found


def check_plan(plan, step=0.2):
    """List of problems found: (time, hand name, what was hit)."""
    job = plan.job
    problems = []
    for t in np.arange(0, plan.duration, step):
        boxes = []
        for part in range(len(job.parts())):
            off = plan.part_offset(part, t)
            for b in job.part_boxes(part):
                boxes.append((b[0] + off[0], b[1] + off[0], b[2] + off[1], b[3] + off[1],
                              b[4] + off[2], b[5] + off[2]))
        for track in (plan.tc, plan.th):
            g, q = track.at(t)
            pts = arm_points(track.hand, g, q)
            if track is plan.th:      # the magnet touches the part it carries: skip its last 3 cm
                pts = pts[:-2]
            if np.any(pts[:, 2] < BED_Z - 0.01):
                problems.append((round(t, 1), track.hand.name, "below the bed"))
            for k in hits(pts, boxes):
                problems.append((round(t, 1), track.hand.name, f"steel box {k}"))
    return problems
