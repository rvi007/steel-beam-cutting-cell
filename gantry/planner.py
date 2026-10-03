"""
The planner: turns a Job into a timed motion plan for BOTH hands.

How a job runs (part by part, from X = 0 towards the far end):
  1. Cutter cuts the part's holes, slots and notches (top-flange work first, then the web).
  2. Cutter goes to the cut-off and waits; Handler comes in and grips the part (magnet).
  3. Cutter cuts the whole profile: top flange, web, bottom flange (+Y half, then -Y half).
  4. Handler lifts the free part, carries it to the outfeed rack and puts it down,
     while the Cutter is already moving on to the next part.

Safety rules the planner enforces:
  - Bridges never closer than MIN_GAP (they share the rails). A move that would break
    this waits for the other hand, or the other hand backs off first.
  - Long moves go up to Z_SAFE first, travel, then come down.
  - The torch always comes in and leaves along its own axis, starting from a point
    clear of the beam (outside the flange for side cuts).
"""
import numpy as np

from gantry.beam import DIAG_N, DOWN, cut_speed
from gantry.machine import BEAM_Y, MIN_GAP, OUTFEED_Y, Z_SAFE, make_hands, move_time

DT = 0.1                  # time between plan samples (s)
PIERCE_S = 0.6            # torch waits this long to pierce the steel
MAGNET_S = 0.5            # time for the magnet to grip / let go
APPROACH_SPEED = 0.10     # m/s, slow move onto / off the steel
LIFT = 0.25               # how high the Handler lifts a part to carry it


def column_side(d):
    """Which way the Cutter's column should stand off from the tool tip, per torch direction."""
    if np.allclose(d, DOWN):
        return np.array([1.0, 0, 0])
    if np.allclose(d, DIAG_N):
        return np.array([0.45, -0.9, 0])
    return np.array([0.45, 0.9, 0])        # SIDE and DIAG_P: column on the +Y side


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
        inside = x[(t >= t0) & (t <= t1)]
        ends = np.interp([t0, t1], t, x)
        xs = np.concatenate([inside, ends])
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


class Plan:
    def __init__(self, job):
        self.job = job
        self.cutter, self.handler = make_hands()
        rest_c = self.cutter.preference(DOWN, column_side(DOWN))[1]
        rest_h = self.handler.preference(DOWN, [-1, 0, 0])[1]
        self.tc = Track(self.cutter, rest_c)
        self.th = Track(self.handler, rest_h)
        self.cuts = []          # each torch pass: hand, feature, points, times
        self.feature_done = {}  # feature index -> time it was finished
        self.carries = []       # parts moved by the Handler
        self.steps = []         # (time, text) for the status line
        self.warnings = []
        self.near = None        # Cutter at an approach point with this torch direction

    # ------------------------------------------------------------------ helpers
    def _say(self, t, text, who=None):
        """Remember what a hand starts doing at time t (shown in the status line)."""
        if who is None:
            who = text.split(":")[0] if text.split(":")[0] in ("Cutter", "Handler") else "Cutter"
        self.steps.append((t, who, text.split(": ", 1)[-1]))

    def _other(self, track):
        return self.th if track is self.tc else self.tc

    def _commit(self, track, samples, start=None):
        """Add a motion, delaying it (or moving the other hand away) so the bridges
        never get closer than MIN_GAP. Returns the time it starts."""
        start = track.end if start is None else max(start, track.end)
        if not samples:
            return start
        other = self._other(track)
        xs = [s[1][0] for s in samples] + [track.g[-1][0]]
        dur = samples[-1][0]
        for attempt in range(3):
            # check against everything the other hand does from now on: once we
            # arrive we stay there, so its later moves must also keep clear
            lo, hi = other.x_range(start, max(start + dur, other.end))
            if track is self.tc:
                ok = hi <= min(xs) - MIN_GAP + 1e-9
            else:
                ok = lo >= max(xs) + MIN_GAP - 1e-9
            if ok:
                track.add(samples, start)
                return start
            if attempt == 0:
                start = max(start, other.end)          # wait until the other hand is idle
            else:                                      # make the other hand back off
                g, q = other.g[-1].copy(), other.q[-1].copy()
                g[0] = min(xs) - MIN_GAP - 0.05 if track is self.tc else max(xs) + MIN_GAP + 0.05
                g[2] = Z_SAFE
                back = self._joint_move(other.g[-1], other.q[-1], g, q, other.hand)
                other.add(back, other.end)
                self._say(other.end, f"{other.hand.name}: backing off to keep the bridges apart")
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
            q, ep, ed = hand.solve(g, p, d, q)
            worst = max(worst, ep)
            if i:
                t += np.linalg.norm(points[i] - points[i - 1]) / speed
            samples.append((t, g, q))
        if worst > 0.001:
            self.warnings.append(f"{hand.name}: {label} misses by {worst * 1000:.1f} mm (out of reach)")
        return samples, q

    def _go(self, track, g, q, direct=False, start=None):
        """Move a hand to (g, q). Unless `direct`, go up to Z_SAFE, travel, come down."""
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

    def _approach_distance(self, d):
        if np.allclose(d, DOWN):
            return 0.06
        return (self.job.p["b"] / 2 + 0.06) / abs(d[1])

    # ------------------------------------------------------------------ cutter
    def _cutter_to(self, pts, d):
        """Bring the torch to the approach point of a cut. Returns (g, q at approach)."""
        hand = self.cutter
        g, q_pref = hand.place(pts.mean(axis=0), d, column_side(d))
        a0 = pts[0] - d * self._approach_distance(d)
        q, ep, _ = hand.solve(g, a0, d, q_pref)
        if ep > 0.001:
            self.warnings.append(f"Cutter cannot reach the start of a cut at x={pts[0][0]:.2f}")
        g_now = self.tc.g[-1]
        direct = (self.near is not None and np.allclose(self.near, d)
                  and np.linalg.norm(g - g_now) < 1.5)
        self._go(self.tc, g, q, direct=direct)
        return g, q

    def _cutter_cut(self, g, q, pts, d, thick, feature, label):
        """Approach, pierce, cut along the path, retract. Leaves the torch at the
        retract point (self.near = d)."""
        hand = self.cutter
        app = self._approach_distance(d)
        a0 = pts[0] - d * app
        a1 = pts[-1] - d * app
        s, q = self._line(hand, g, q, np.linspace(a0, pts[0], 10), d, APPROACH_SPEED, label)
        self._commit(self.tc, s)
        t_on = self.tc.end
        self.tc.hold(t_on + PIERCE_S)
        s, q = self._line(hand, g, q, pts, d, cut_speed(thick), label)
        t_start = self._commit(self.tc, s)
        self.cuts.append({"hand": "Cutter", "feature": feature, "points": pts,
                          "times": t_start + np.array([x[0] for x in s]), "t_on": t_on})
        s, q = self._line(hand, g, q, np.linspace(pts[-1], a1, 10), d, APPROACH_SPEED * 2, label)
        self._commit(self.tc, s)
        self.near = d

    # ------------------------------------------------------------------ handler
    def _grip_point(self, part):
        x0, x1 = self.job.parts()[part]
        x = (x0 + x1) / 2
        for a, b, _ in self.job.notches(part):        # keep the magnet off a notch
            if a - 0.06 < x < b + 0.06:
                x = b + 0.06 if a <= x0 + 1e-9 else a - 0.06
        return np.array([x, BEAM_Y, self.job.z_top])

    def _handler_pick(self, part, cutter_min_x):
        """Handler grips the part. Returns the time it has hold, or None if it can't."""
        hand = self.handler
        p = self._grip_point(part)
        g, q = hand.place(p, DOWN, [-1, 0, 0])
        if g[0] > cutter_min_x - MIN_GAP:          # too close to the Cutter: reach further
            g[0] = cutter_min_x - MIN_GAP
        above = p + [0, 0, 0.12]
        q_above, ep, _ = hand.solve(g, above, DOWN, q)
        q_grip, ep2, _ = hand.solve(g, p, DOWN, q_above)
        if max(ep, ep2) > 0.002:
            self.warnings.append(f"Handler cannot reach part {part + 1}; it stays on the bed")
            return None, None
        self._say(max(self.th.end, self.tc.end), f"Handler: moving in to hold part {part + 1}")
        self._go(self.th, g, q_above, start=self.tc.end)   # only once the Cutter is in place
        s, _ = self._line(hand, g, q_above, np.linspace(above, p, 10), DOWN, APPROACH_SPEED, "grip")
        self._commit(self.th, s)
        self.th.hold(self.th.end + MAGNET_S)
        self._say(self.th.end, f"Handler: holding part {part + 1} while it is cut free")
        return self.th.end, (g, q_grip)

    def _handler_carry(self, part, t_free, g, q):
        """Lift the free part, carry it to the outfeed rack, put it down, let go."""
        hand = self.handler
        t_grip = self.th.end
        self.th.hold(t_free)
        self._say(t_free, f"Handler: carrying part {part + 1} ({self.job.weight(part):.0f} kg) to the outfeed rack")
        up = g + [0, 0, LIFT]
        over = up + [0, OUTFEED_Y - BEAM_Y, 0]
        down = over - [0, 0, LIFT]
        for a, b in ((g, up), (up, over), (over, down)):
            self._commit(self.th, self._joint_move(a, q, b, q, hand))
        t_release = self.th.end
        self.th.hold(t_release + MAGNET_S)
        self._go(self.th, np.array([down[0], down[1], Z_SAFE]), q, direct=True)
        self.carries.append({"part": part, "t_grip": t_grip, "t_free": t_free,
                             "t_release": t_release, "offset": down - g})

    # ------------------------------------------------------------------ main
    def build(self):
        job = self.job
        order = {"top": 0, "web": 1}
        for part, (x0, x1) in enumerate(job.parts()):
            feats = [i for i, f in enumerate(job.features)
                     if job.part_of(f) == part and f["type"] != "cut" and not job.check(f)]
            feats.sort(key=lambda i: (job.features[i]["type"] == "notch",
                                      order.get(job.features[i].get("face"), 0), job.features[i]["x"]))
            for i in feats:
                f = job.features[i]
                self._say(self.tc.end, f"Cutter: {f['type']} at x = {f['x']:.3f} m (part {part + 1})")
                for pts, d, thick in job.paths(f):
                    g, q = self._cutter_to(pts, d)
                    self._cutter_cut(g, q, pts, d, thick, i, f["type"])
                self.feature_done[i] = self.tc.end

            cut = [i for i, f in enumerate(job.features)
                   if f["type"] == "cut" and abs(f["x"] - x1) < 1e-9 and not job.check(f)]
            is_remnant = not feats and part == len(job.parts()) - 1 and part > 0
            if is_remnant:
                self._say(self.tc.end, f"Cutter: part {part + 1} is the remnant - it stays on the bed")
                continue
            heavy = job.weight(part) > self.handler.payload_kg
            if heavy:
                self.warnings.append(f"Part {part + 1} weighs {job.weight(part):.0f} kg - too heavy "
                                     f"for the Handler ({self.handler.payload_kg:.0f} kg); left for the crane")
            segs = job.paths(job.features[cut[0]]) if cut else []
            placements = [self.cutter.place(p.mean(axis=0), d, column_side(d))[0] for p, d, _ in segs]
            grip = None
            if segs:
                self._say(self.tc.end, f"Cutter: cut-off at x = {x1:.3f} m")
                g, q = self._cutter_to(segs[0][0], segs[0][1])
            if not heavy and not segs:
                # no cut-off (last piece): the Cutter goes home so the Handler can get in
                self._say(self.tc.end, "Cutter: moving out of the way")
                self.near = None
                self._go(self.tc, self.cutter.park, self.tc.q[0])
            if not heavy:
                min_x = min([pl[0] for pl in placements] + [self.tc.g[-1][0]])
                t_hold, grip = self._handler_pick(part, min_x)
                if t_hold is not None:
                    self.tc.hold(t_hold)
            for k, (pts, d, thick) in enumerate(segs):
                if k:
                    g, q = self._cutter_to(pts, d)
                self._cutter_cut(g, q, pts, d, thick, cut[0], "cut-off")
            if segs:
                self.feature_done[cut[0]] = self.tc.end
            if grip is not None:
                self._handler_carry(part, self.tc.end, *grip)

        self._say(self.tc.end, "Cutter: going home")
        self._say(self.th.end, "Handler: going home")
        self.near = None
        self._go(self.tc, self.cutter.park, self.tc.q[0])
        self._go(self.th, self.handler.park, self.th.q[0])
        end = max(self.tc.end, self.th.end)
        self.tc.hold(end)
        self.th.hold(end)
        self.tc.finish()
        self.th.finish()
        self.duration = end
        self._say(end, "job finished", "Cutter")
        self._say(end, "job finished", "Handler")
        self.steps.sort(key=lambda s: s[0])
        return self

    # ------------------------------------------------------------------ queries
    def step_at(self, t, who="Cutter"):
        """What a hand is doing at time t."""
        text = "waiting" if who == "Handler" else ""
        for ts, w, msg in self.steps:
            if ts <= t + 1e-9 and w == who:
                text = msg
        return text

    def part_offset(self, part, t):
        """How far a part has been moved by the Handler at time t."""
        for c in self.carries:
            if c["part"] == part and t > c["t_free"]:
                if t >= c["t_release"]:
                    return c["offset"]
                g_free, _ = self.th.at(c["t_free"])
                g_now, _ = self.th.at(t)
                return g_now - g_free
        return np.zeros(3)

    def min_gap(self):
        """Closest the two bridges get during the whole plan."""
        t = np.union1d(self.tc.T, self.th.T)
        xc = np.interp(t, self.tc.T, self.tc.G[:, 0])
        xh = np.interp(t, self.th.T, self.th.G[:, 0])
        return float(np.min(xc - xh))

    def summary(self):
        job = self.job
        cut_len = sum(np.sum(np.linalg.norm(np.diff(c["points"], axis=0), axis=1)) for c in self.cuts)
        torch = sum(c["times"][-1] - c["t_on"] for c in self.cuts)
        return (f"cycle time {self.duration / 60:.1f} min, {len(job.parts())} pieces, "
                f"{len(self.cuts)} torch passes\n"
                f"{cut_len:.1f} m of cutting, torch on {torch / 60:.1f} min "
                f"({100 * torch / self.duration:.0f}% of the time)")
