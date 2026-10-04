"""
The planner: turns a nested stock bar into a timed motion plan for BOTH hands.

How a bar runs (part by part, from X = 0 towards the far end):
  1. Cutter squares the part's start (trim cut or the cut after a gap), unless it shares
     the previous part's cut-off.
  2. Cutter cuts the holes, slots and openings in order along the bar, one bolt group at a
     time (top hole first) - never jumping back and forth.
  3. Cutter goes to the cut-off and waits; Handler comes in and grips the part (magnet).
  4. Cutter cuts the cut-off through every face.
  5. Handler lifts the free part and puts it on the outfeed table, while the Cutter is
     already working on the next part. Offcuts fall between the rollers into the scrap tray; the remnant stays on the
     rollers if it spans two of them, otherwise it falls too.

Torch passes per face (machine Y+ is the Cutter's side, see sections.py for how parts lie):
    top flange              straight down
    web / upright leg       from the +Y side, between the flanges
    bottom flange           torch tilted 45 deg, from each side of the web (I) or the open side (channel)
    flat leg of an angle    straight down; the heel corner with the torch tilted 45 deg

Safety rules:
  - Bridges never closer than MIN_GAP (they share the rails): a move waits for the other
    hand, or the other hand backs off first.
  - Long moves go up to Z_SAFE, travel, then come down.
  - The torch comes in and leaves along its own axis, from a point outside the section.
"""
import math

import numpy as np

from beamcell import sections as S
from beamcell.machine import (BEAM_Y, BED_Z, MIN_GAP, OUTFEED_Y, SCRAP_TRAY_Z, X_LIMITS, Y_LIMITS, Z_LIMITS, Z_SAFE,
                              fall_time, make_hands, move_time, supported_on_rollers)
from beamcell.parts import inside

DT = 0.1                  # time between plan samples (s)
PIERCE_S = 0.6            # torch waits this long to pierce the steel
MAGNET_S = 0.5            # time for the magnet to grip / let go
APPROACH_SPEED = 0.10     # m/s, slow move onto / off the steel
LIFT = 0.25               # how high the Handler lifts a part to carry it
STANDOFF = 0.003          # torch tip height above the steel (m)
STEP_MM = 3.0             # spacing of path points along a cut
KERF_COMP = 1.0           # holes are cut 1 mm inside the line (half the kerf)
TRACK_OVER = 0.15         # cuts longer than this (m): the gantry travels with the torch

R2 = math.sqrt(2)
DIRS = {"D": np.array([0.0, 0.0, -1.0]),          # straight down
        "S": np.array([0.0, -1.0, 0.0]),          # from the +Y side
        "P": np.array([0.0, -1.0, -1.0]) / R2,    # tilted, from +Y and above
        "N": np.array([0.0, 1.0, -1.0]) / R2}     # tilted, from -Y and above
DOWN = DIRS["D"]


def cut_speed(thickness_mm):
    """Plasma cutting speed (m/s) for a thickness - typical 130 A values."""
    t = thickness_mm
    return 0.050 if t <= 6 else 0.040 if t <= 10 else 0.028 if t <= 15 else 0.018 if t <= 20 else 0.010


def column_side(d):
    """Which way the Cutter's column stands off from the tool tip, per torch direction."""
    if np.allclose(d, DOWN):
        return np.array([1.0, 0, 0])
    if np.allclose(d, DIRS["N"]):
        return np.array([0.45, -0.9, 0])
    return np.array([0.45, 0.9, 0])


def smooth(n):
    """0..1 with gentle start and stop (like a real motion controller)."""
    s = np.linspace(0, 1, n)
    return s * s * s * (10 - 15 * s + 6 * s * s)


class Track:
    """The timed path of one hand: time, gantry (x,y,z), 6 joint angles."""

    def __init__(self, hand, q):
        self.hand = hand
        self.t = [0.0]
        self.g = [hand.park.copy()]
        self.q = [np.array(q, float)]

    @property
    def end(self):
        return self.t[-1]

    def hold(self, until):
        if until > self.end + 1e-9:
            self.t.append(until)
            self.g.append(self.g[-1].copy())
            self.q.append(self.q[-1].copy())

    def add(self, samples, start):
        """samples: list of (time after start, g, q)."""
        self.hold(start)
        for dt, g, q in samples:
            if dt > 0:
                self.t.append(start + dt)
                self.g.append(np.array(g, float))
                self.q.append(np.array(q, float))

    def x_range(self, t0, t1):
        """Lowest and highest bridge X between t0 and t1."""
        t = np.array(self.t)
        x = np.array([g[0] for g in self.g])
        xs = np.concatenate([x[(t >= t0) & (t <= t1)], np.interp([t0, t1], t, x)])
        return xs.min(), xs.max()

    def finish(self):
        self.T = np.array(self.t)
        self.G = np.array(self.g)
        self.Q = np.array(self.q)

    def at(self, t):
        """Gantry and joints at time t (after finish())."""
        i = int(np.clip(np.searchsorted(self.T, t) - 1, 0, len(self.T) - 2))
        t0, t1 = self.T[i], self.T[i + 1]
        a = 0.0 if t1 <= t0 else float(np.clip((t - t0) / (t1 - t0), 0, 1))
        return self.G[i] + a * (self.G[i + 1] - self.G[i]), self.Q[i] + a * (self.Q[i + 1] - self.Q[i])

    def to_json(self):
        return {"t": np.round(self.T, 3).tolist(), "g": np.round(self.G, 4).tolist(),
                "q": np.round(self.Q, 4).tolist()}


# ------------------------------------------------------------------ part -> machine coordinates
class Placed:
    """A part lying on the bed at x0 mm along the bar."""

    def __init__(self, part, x0):
        self.part = part
        self.s = part.sec
        self.x0 = x0

    def world(self, x, u, v):
        """Bar x, section u, v (mm) -> machine point (m)."""
        return np.array([(self.x0 + x) / 1000, BEAM_Y + u / 1000, BED_Z + v / 1000])

    def classify(self, face, x, y):
        """Where the torch works for a point on a face: (direction key, surface point, thickness mm),
        or None where another pass covers it (e.g. the web where a flange is cut)."""
        s, k = self.s, self.s["kind"]
        h, b, tw, tf = s["h"], s["b"], s["tw"], s["tf"]
        c = S.face_to_section(s, face, y)
        if face in ("v", "h"):
            v = c
            if k == "L":
                t = s["t"]
                if v >= t + 4:
                    return "S", self.world(x, b / 2, v), t
                return "P", self.world(x, b / 2, max(v, 2.0)), t * R2      # heel corner, tilted
            if tf - 4 <= v <= h - tf + 4:
                return "S", self.world(x, tw / 2 if k == "I" else b / 2, v), tw
            return None
        if face == "o":
            return "D", self.world(x, c, h), tf
        u = c                                                              # face "u"
        if k == "L":
            t = s["t"]
            if u >= b / 2 - t - 3:
                return None                                                # under the upright leg
            return "D", self.world(x, u, t), t
        if k == "I":
            if abs(u) <= tw / 2 + 6:
                return None
            return ("P" if u > 0 else "N"), self.world(x, u, tf), tf * R2
        if u >= b / 2 - tw - 6:                                            # channel: web zone
            return None
        return "N", self.world(x, u, tf), tf * R2

    def passes(self, face, pts, closed=False):
        """A path in face coordinates -> torch passes [(tip points, dir key, thickness)]."""
        dense = _densify(pts, STEP_MM)
        runs, cur = [], None
        for x, y in dense:
            c = self.classify(face, x, y)
            if c is None:
                cur = None
                continue
            key, surf, thick = c
            tip = surf - DIRS[key] * STANDOFF
            if cur is None or cur[1] != key:
                cur = [[tip], key, thick]
                runs.append(cur)
            else:
                cur[0].append(tip)
        return [(np.array(r[0]), r[1], r[2]) for r in runs if len(r[0]) >= 2]


def _densify(pts, step):
    out = [tuple(pts[0])]
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(math.hypot(x2 - x1, y2 - y1) / step)))
        out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(1, n + 1)]
    return out


def hole_path(hole):
    """Pierce in the middle, lead in to the edge, once round plus a little overlap.
    Round holes and slots, in face coordinates (mm)."""
    r = hole["d"] / 2 - KERF_COMP
    straight = max((hole.get("slot") or 0) - hole["d"], 0.0)
    a = math.radians(hole.get("angle", 0) or 0)
    pts = []
    if straight <= 0:
        n = max(16, int(2 * math.pi * r / STEP_MM))
        pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
        pts += [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(1, n // 12 + 2)]
    else:
        L = straight / 2
        n = max(8, int(math.pi * r / STEP_MM))
        pts += [(L + r * math.cos(t), r * math.sin(t)) for t in np.linspace(-math.pi / 2, math.pi / 2, n)]
        pts += [(-L + r * math.cos(t), r * math.sin(t)) for t in np.linspace(math.pi / 2, 3 * math.pi / 2, n)]
        pts += [(L, -r), (L + r * 0.5, -r * 0.87)]
    lead = [(pts[0][0] * f, pts[0][1] * f) for f in np.linspace(0, 1, 5)[:-1]]
    pts = lead + pts
    ca, sa = math.cos(a), math.sin(a)
    return [(hole["x"] + x * ca - y * sa, hole["y"] + x * sa + y * ca) for x, y in pts]


def opening_path(points):
    pts = [tuple(p) for p in points]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return [(cx, cy), ((cx + pts[0][0]) / 2, (cy + pts[0][1]) / 2)] + pts + [pts[0], pts[1]]


FACE_ORDER = {"o": 0, "v": 1, "h": 1, "u": 2}
GROUP_MM = 150.0          # features closer than this along the bar are one group (e.g. a bolt group)


def _in_order(ops):
    """Holes and openings in the order a person would cut them: along the bar from the start,
    one group at a time; inside a group, one torch direction at a time, top hole first."""
    if not ops:
        return ops
    x = lambda o: float(np.mean(o["passes"][0][0][:, 0]))             # noqa: E731
    ops = sorted(ops, key=x)
    groups, cur = [], [ops[0]]
    for o in ops[1:]:
        if (x(o) - x(cur[-1])) * 1000 <= GROUP_MM:
            cur.append(o)
        else:
            groups.append(cur)
            cur = [o]
    groups.append(cur)
    out = []
    for g in groups:
        out += sorted(g, key=lambda o: ("DSPN".index(o["passes"][0][1]), -round(float(np.max(o["passes"][0][0][:, 2])), 3), x(o)))
    return out


def bar_operations(bar):
    """Everything the Cutter has to do on a bar, part by part.
    Returns (ops per placement, warnings); an op is {kind, label, passes, ...}."""
    all_ops, warnings = [], []
    for k, pl in enumerate(bar.placements):
        part = bar.parts[pl["part"]]
        placed = Placed(part, pl["x0"])
        bad_holes = {int(i["item"].split()[1]) - 1 for i in part.check()
                     if i["level"] == "error" and i["item"].startswith("hole ") and "&" not in i["item"]}
        ops = []
        for i, hole in enumerate(part.holes):
            if i in bad_holes:
                warnings.append(f"{part.mark}: hole {i + 1} skipped (it breaks a rule - see the part checks)")
                continue
            face = part.hole_face(hole)
            ps = placed.passes(face, hole_path(hole))
            if len(ps) != 1:
                warnings.append(f"{part.mark}: hole {i + 1} can't be reached by the torch")
                continue
            kind = "slot" if hole.get("slot") else "hole"
            ops.append({"kind": kind, "hole": i, "face": face, "label": f"{kind} {i + 1} (face {face})", "passes": ps})
        for i, item in enumerate(part.inner):
            ps = placed.passes(part.norm_face(item["face"]), opening_path(item["points"]))
            if len(ps) != 1:
                warnings.append(f"{part.mark}: opening {i + 1} can't be reached by the torch")
                continue
            ops.append({"kind": "opening", "opening": i, "face": item["face"], "label": f"opening {i + 1}", "passes": ps})
        ops = _in_order(ops)
        for end in ("start", "end"):
            if end == "start" and pl["start_shared"]:
                continue
            if end == "end" and pl["x1"] >= bar.length - 0.5:
                continue
            passes = []
            for face in sorted(part.faces(), key=lambda f: FACE_ORDER[f]):
                for ch in part.chains(face):
                    if ch["end"] == end:
                        passes += sorted(placed.passes(face, ch["points"]), key=lambda p: "DSPN".index(p[1]))
            if passes:
                op = {"kind": end, "label": "start cut" if end == "start" else "cut-off", "passes": passes}
                if end == "start":
                    ops.insert(0, op)                  # square the end first, then the holes, then cut off
                else:
                    ops.append(op)
        for i, op in enumerate(ops):
            op["id"] = f"{k}.{i}"
            op["placement"] = k
        all_ops.append(ops)
    return all_ops, warnings


# ------------------------------------------------------------------ the plan
class Plan:
    def __init__(self, bar):
        self.bar = bar
        self.cutter, self.handler = make_hands()
        rest_c = self.cutter.preference(DOWN, column_side(DOWN))[1]
        rest_h = self.handler.preference(DOWN, [-1, 0, 0])[1]
        self.tc = Track(self.cutter, rest_c)
        self.th = Track(self.handler, rest_h)
        self.cuts = []          # each torch pass: op, placement, points, times
        self.ops = []           # every operation with its finish time
        self.carries = []       # parts moved by the Handler
        self.drops = []         # pieces falling into the scrap tray: {x0, x1 (mm), t (cut free), t_land}
        self.steps = []         # (time, who, text) for the status line
        self.warnings = []
        self.near = None        # Cutter waiting at an approach point with this torch direction

    # ---------------------------------------------------------------- helpers
    def _say(self, t, who, text):
        self.steps.append((t, who, text))

    def _other(self, track):
        return self.th if track is self.tc else self.tc

    def _commit(self, track, samples, start=None):
        """Add a motion, delaying it (or moving the other hand away) so the bridges never get
        closer than MIN_GAP. Returns the time it starts."""
        start = track.end if start is None else max(start, track.end)
        if not samples:
            return start
        other = self._other(track)
        xs = [s[1][0] for s in samples] + [track.g[-1][0]]
        dur = samples[-1][0]
        for attempt in range(3):
            # check against everything the other hand does from now on: once we arrive
            # we stay there, so its later moves must also keep clear
            lo, hi = other.x_range(start, max(start + dur, other.end))
            ok = hi <= min(xs) - MIN_GAP + 1e-9 if track is self.tc else lo >= max(xs) + MIN_GAP - 1e-9
            if ok:
                track.add(samples, start)
                return start
            if attempt == 0:
                start = max(start, other.end)          # wait until the other hand is idle
            else:                                      # make the other hand back off
                g, q = other.g[-1].copy(), other.q[-1].copy()
                g[0] = min(xs) - MIN_GAP - 0.05 if track is self.tc else max(xs) + MIN_GAP + 0.05
                g[2] = Z_SAFE
                other.add(self._joint_move(other.g[-1], other.q[-1], g, q, other.hand), other.end)
                self._say(other.end, other.hand.name, "backing off to keep the bridges apart")
                start = max(start, other.end)
        raise RuntimeError("could not keep the bridges apart")

    @staticmethod
    def _joint_move(g0, q0, g1, q1, hand):
        T = move_time(g0, g1, q0, q1, hand.arm.joint_speed)
        n = max(3, int(np.ceil(T / DT)) + 1)
        s = smooth(n)
        g0, g1, q0, q1 = map(np.asarray, (g0, g1, q0, q1))
        return [(T * i / (n - 1), g0 + s[i] * (g1 - g0), q0 + s[i] * (q1 - q0)) for i in range(n)]

    def _line(self, hand, g, q, points, d, speed, label):
        """Tool tip along `points` (arm only, gantry still). Returns samples and final q."""
        samples, t, worst = [], 0.0, 0.0
        for i, p in enumerate(points):
            q, ep, _ = hand.solve(g, p, d, q)
            worst = max(worst, ep)
            if i:
                t += np.linalg.norm(points[i] - points[i - 1]) / speed
            samples.append((t, g, q))
        if worst > 0.001:
            self.warnings.append(f"{hand.name}: {label} misses by {worst * 1000:.1f} mm (out of reach)")
        return samples, q

    def _go(self, track, g, q, direct=False, start=None):
        """Move a hand to (g, q). Unless `direct`: up to Z_SAFE, travel, come down."""
        if start is not None:
            track.hold(start)
        g0, q0 = track.g[-1], track.q[-1]
        hand = track.hand
        if direct:
            self._commit(track, self._joint_move(g0, q0, g, q, hand))
            return
        up = np.array([g0[0], g0[1], Z_SAFE])
        high = np.array([g[0], g[1], Z_SAFE])
        if g0[2] < Z_SAFE - 1e-6:
            self._commit(track, self._joint_move(g0, q0, up, q0, hand))
        self._commit(track, self._joint_move(up, q0, high, q, hand))
        self._commit(track, self._joint_move(high, q, g, q, hand))

    def _approach(self, d, p):
        """How far back along the torch axis to start, so the torch begins outside the section."""
        if np.allclose(d, DOWN):
            return 0.06
        s = self.bar.parts[0].sec
        half = s["b"] / 2000
        if d[1] < 0:      # coming from +Y
            out = (BEAM_Y + half) - p[1]
        else:
            out = p[1] - (BEAM_Y - half)
        return (max(out, 0.0) + 0.06) / abs(d[1])

    # ---------------------------------------------------------------- cutter
    def _gantry_for(self, p, d):
        """Gantry position that keeps the arm in its comfortable pose with the tip at p."""
        offset, q = self.cutter.preference(d, column_side(d))
        g = np.asarray(p) - offset
        return np.clip(g, [X_LIMITS[0], Y_LIMITS[0], Z_LIMITS[0]], [X_LIMITS[1], Y_LIMITS[1], Z_LIMITS[1]]), q

    def _cutter_to(self, pts, d):
        """Torch to the approach point of a cut. Long cuts start with the gantry at the start of
        the cut (it then travels along with the torch); short ones from the middle."""
        hand = self.cutter
        long_cut = np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)) > TRACK_OVER
        g, q_pref = self._gantry_for(pts[0] if long_cut else pts.mean(axis=0), d)
        a0 = pts[0] - d * self._approach(d, pts[0])
        q, ep, _ = hand.solve(g, a0, d, q_pref)
        if ep > 0.001:
            self.warnings.append(f"Cutter can't reach the start of a cut at x={pts[0][0]:.2f} m")
        direct = self.near is not None and np.allclose(self.near, d) and np.linalg.norm(g - self.tc.g[-1]) < 1.5
        self._go(self.tc, g, q, direct=direct)
        return g, q

    def _cutter_cut(self, g, q, pts, d, thick, op):
        hand = self.cutter
        a0 = pts[0] - d * self._approach(d, pts[0])
        s, q = self._line(hand, g, q, np.linspace(a0, pts[0], 10), d, APPROACH_SPEED, op["label"])
        self._commit(self.tc, s)
        t_on = self.tc.end
        self.tc.hold(t_on + PIERCE_S)
        if np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)) > TRACK_OVER:
            # long cut: the gantry moves with the torch (coordinated motion), the arm keeps its pose
            offset = g - pts[0]
            s, worst, t = [], 0.0, 0.0
            for i, p in enumerate(pts):
                gi = p + offset
                q, ep, _ = hand.solve(gi, p, d, q)
                worst = max(worst, ep)
                if i:
                    t += np.linalg.norm(pts[i] - pts[i - 1]) / cut_speed(thick)
                s.append((t, gi, q))
            g = s[-1][1]
            if worst > 0.001:
                self.warnings.append(f"Cutter: {op['label']} misses by {worst * 1000:.1f} mm (out of reach)")
        else:
            s, q = self._line(hand, g, q, pts, d, cut_speed(thick), op["label"])
        t_start = self._commit(self.tc, s)
        self.cuts.append({"op": op["id"], "placement": op["placement"], "points": pts,
                          "times": t_start + np.array([x[0] for x in s]), "t_on": t_on})
        a1 = pts[-1] - d * self._approach(d, pts[-1])
        s, q = self._line(hand, g, q, np.linspace(pts[-1], a1, 10), d, APPROACH_SPEED * 2, op["label"])
        self._commit(self.tc, s)
        self.near = d

    def _do_op(self, op, first_go=None):
        for i, (pts, key, thick) in enumerate(op["passes"]):
            d = DIRS[key]
            if i == 0 and first_go is not None:
                g, q = first_go
            else:
                g, q = self._cutter_to(pts, d)
            self._cutter_cut(g, q, pts, d, thick, op)
        op["t_done"] = self.tc.end
        self.ops.append(op)

    # ---------------------------------------------------------------- handler
    def _grip_point(self, k):
        pl = self.bar.placements[k]
        part = self.bar.parts[pl["part"]]
        s = part.sec
        face = "u" if s["kind"] == "L" else "o"
        if s["kind"] == "L":
            u = (-s["b"] / 2 + (s["b"] / 2 - s["t"])) / 2
            v = s["t"]
        else:
            u, v = 0.0, s["h"]
        y = S.section_to_face(s, face, u)
        outline = part.face_outline(face)
        holes = [h for h in part.holes if part.hole_face(h) == face]
        L = part.length
        for off in [0] + [sgn * k_ * 40 for k_ in range(1, int(L / 80) + 1) for sgn in (1, -1)]:
            x = L / 2 + off
            if not (60 <= x <= L - 60) or not inside(outline, x, y):
                continue
            if any(not inside(outline, x + dx, y) for dx in (-60, 60)):
                continue
            if all(math.hypot(h["x"] - x, h["y"] - y) > 60 + h["d"] for h in holes):
                return Placed(part, pl["x0"]).world(x, u, v)
        return Placed(part, pl["x0"]).world(L / 2, u, v)

    def _handler_pick(self, k, cutter_min_x):
        hand = self.handler
        p = self._grip_point(k)
        g, q = hand.place(p, DOWN, [-1, 0, 0])
        if g[0] > cutter_min_x - MIN_GAP:            # too close to the Cutter: reach further
            g[0] = cutter_min_x - MIN_GAP
        above = p + [0, 0, 0.12]
        q_above, ep, _ = hand.solve(g, above, DOWN, q)
        q_grip, ep2, _ = hand.solve(g, p, DOWN, q_above)
        mark = self.bar.parts[self.bar.placements[k]["part"]].mark
        if max(ep, ep2) > 0.002:
            self.warnings.append(f"Handler can't reach {mark}; it stays on the bed")
            return None, None
        self._say(max(self.th.end, self.tc.end), "Handler", f"moving in to hold {mark}")
        self._go(self.th, g, q_above, start=self.tc.end)
        s, _ = self._line(hand, g, q_above, np.linspace(above, p, 10), DOWN, APPROACH_SPEED, "grip")
        self._commit(self.th, s)
        self.th.hold(self.th.end + MAGNET_S)
        self._say(self.th.end, "Handler", f"holding {mark} while it is cut free")
        return self.th.end, (g, q_grip)

    def _handler_carry(self, k, t_free, g, q):
        hand = self.handler
        t_grip = self.th.end
        self.th.hold(t_free)
        part = self.bar.parts[self.bar.placements[k]["part"]]
        self._say(t_free, "Handler", f"carrying {part.mark} ({part.weight:.0f} kg) to the outfeed table")
        up = g + [0, 0, LIFT]
        over = up + [0, OUTFEED_Y - BEAM_Y, 0]
        down = over - [0, 0, LIFT]
        for a, b in ((g, up), (up, over), (over, down)):
            self._commit(self.th, self._joint_move(a, q, b, q, hand))
        t_release = self.th.end
        self.th.hold(t_release + MAGNET_S)
        self._say(self.th.end, "Handler", f"{part.mark} is on the outfeed table - waiting")
        self._go(self.th, np.array([down[0], down[1], Z_SAFE]), q, direct=True)
        self.carries.append({"placement": k, "t_grip": t_grip, "t_free": t_free, "t_release": t_release,
                             "offset": (down - g).tolist()})

    def _drop(self, x0, x1, t, remnant=False):
        """A loose piece falls between the rollers into the scrap tray (straight down, gravity)."""
        self.drops.append({"x0": x0, "x1": x1, "t": t, "t_land": t + fall_time(BED_Z - SCRAP_TRAY_Z),
                           "remnant": remnant})
        self._say(t, "Cutter", "short remnant falls into the scrap tray" if remnant else "offcut falls into the scrap tray")

    # ---------------------------------------------------------------- main
    def build(self):
        bar = self.bar
        all_ops, warnings = bar_operations(bar)
        self.warnings += warnings
        scraps = {round(x1, 3): (x0, x1) for x0, x1 in bar.scraps}
        for k, pl in enumerate(bar.placements):
            part = bar.parts[pl["part"]]
            ops = all_ops[k]
            for op in [o for o in ops if o["kind"] == "start"]:
                self._say(self.tc.end, "Cutter", f"{part.mark}: start cut")
                self._do_op(op)
                if round(pl["x0"], 3) in scraps:
                    x0, x1 = scraps[round(pl["x0"], 3)]
                    self._drop(x0, x1, op["t_done"])
            for op in [o for o in ops if o["kind"] not in ("start", "end")]:
                self._say(self.tc.end, "Cutter", f"{part.mark}: {op['label']}")
                self._do_op(op)
            end_ops = [o for o in ops if o["kind"] == "end"]
            keep = pl.get("keep", False)             # manual cutting: the rest of the bar stays on the bed
            scrap = pl.get("scrap", False)           # manual cutting: a piece too short to keep
            loose = keep or scrap
            heavy = not loose and part.weight > self.handler.payload_kg
            if heavy:
                self.warnings.append(f"{part.mark} weighs {part.weight:.0f} kg - more than the Handler's "
                                     f"{self.handler.payload_kg:.0f} kg; left on the bed for the crane")
            first, min_x = None, self.tc.g[-1][0]
            if end_ops:
                op = end_ops[0]
                placements = [self.cutter.place(p.mean(axis=0), DIRS[key], column_side(DIRS[key]))[0]
                              for p, key, _ in op["passes"]]
                self._say(self.tc.end, "Cutter", f"{part.mark}: cut-off")
                first = self._cutter_to(op["passes"][0][0], DIRS[op["passes"][0][1]])
                min_x = min([pl_[0] for pl_ in placements] + [self.tc.g[-1][0]])
            elif not heavy and not loose:
                self._say(self.tc.end, "Cutter", "moving out of the way")
                self.near = None
                self._go(self.tc, self.cutter.park, self.tc.q[0])
                min_x = self.cutter.park[0]
            grip = None
            if not heavy and not loose:
                t_hold, grip = self._handler_pick(k, min_x)
                if t_hold is not None:
                    self.tc.hold(t_hold)
            if end_ops:
                self._do_op(end_ops[0], first_go=first)
            if heavy and not supported_on_rollers((pl["x0"]) / 1000, pl["x1"] / 1000):
                self.warnings.append(f"{part.mark} is too short to stay on the rollers and too heavy to lift - "
                                     "it would fall: support it before the cut-off")
            if scrap or (keep and not supported_on_rollers(pl["x0"] / 1000, pl["x1"] / 1000)):
                self._drop(pl["x0"], pl["x1"], self.tc.end, remnant=keep)
            if grip is not None:
                self._handler_carry(k, self.tc.end, *grip)

        rem = bar.remnant
        if rem and not supported_on_rollers(rem[0] / 1000, rem[1] / 1000):
            self._drop(rem[0], rem[1], self.tc.end, remnant=True)          # too short to stay on the bed
        self._say(self.tc.end, "Cutter", "going home")
        self._say(self.th.end, "Handler", "going home")
        self.near = None
        self._go(self.tc, self.cutter.park, self.tc.q[0])
        self._go(self.th, self.handler.park, self.th.q[0])
        end = max(self.tc.end, self.th.end)
        self.tc.hold(end)
        self.th.hold(end)
        self.tc.finish()
        self.th.finish()
        self.duration = end
        self._say(end, "Cutter", "bar finished")
        self._say(end, "Handler", "bar finished")
        self.steps.sort(key=lambda s: s[0])
        return self

    # ---------------------------------------------------------------- queries
    def step_at(self, t, who="Cutter"):
        text = "waiting" if who == "Handler" else ""
        for ts, w, msg in self.steps:
            if ts <= t + 1e-9 and w == who:
                text = msg
        return text

    def part_offset(self, k, t):
        """How far placement k has been moved by the Handler at time t (m)."""
        for c in self.carries:
            if c["placement"] == k and t > c["t_free"]:
                if t >= c["t_release"]:
                    return np.array(c["offset"])
                return self.th.at(t)[0] - self.th.at(c["t_free"])[0]
        return np.zeros(3)

    def min_gap(self):
        t = np.union1d(self.tc.T, self.th.T)
        return float(np.min(np.interp(t, self.tc.T, self.tc.G[:, 0]) - np.interp(t, self.th.T, self.th.G[:, 0])))

    def summary(self):
        cut_len = sum(np.sum(np.linalg.norm(np.diff(c["points"], axis=0), axis=1)) for c in self.cuts)
        torch = sum(c["times"][-1] - c["t_on"] for c in self.cuts)
        return {"duration_s": round(float(self.duration), 1), "parts": len(self.bar.placements),
                "passes": len(self.cuts), "cut_length_m": round(float(cut_len), 2),
                "torch_on_s": round(float(torch), 1), "min_bridge_gap_m": round(self.min_gap(), 3)}

    def to_json(self):
        return {
            "summary": self.summary(), "warnings": self.warnings,
            "steps": [[round(t, 2), w, m] for t, w, m in self.steps],
            "tracks": {"cutter": self.tc.to_json(), "handler": self.th.to_json()},
            "cuts": [{"op": c["op"], "placement": c["placement"], "t_on": round(c["t_on"], 2),
                      "points": np.round(c["points"], 4).tolist(), "times": np.round(c["times"], 2).tolist()}
                     for c in self.cuts],
            "ops": [{k: op[k] for k in ("id", "placement", "kind", "label", "hole", "opening", "t_done") if k in op}
                    for op in self.ops],
            "carries": self.carries, "drops": self.drops,
        }
