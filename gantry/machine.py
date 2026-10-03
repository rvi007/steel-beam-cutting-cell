"""
The gantry cell: a 12 m long, 3 m wide work area with two overhead hands.

            Y (width, 3 m)
            ^
            |   outfeed rack (finished parts)       y = +0.85
            |   ===================================
            |   steel beam on the bed               y = -0.50
            +-------------------------------------> X (length, 12 m work area)

Each hand = one gantry BRIDGE running along X on the shared rails,
            a CARRIAGE running along the bridge in Y,
            a COLUMN that drops down in Z,
            and a 6-axis ARM hanging upside down under the column.
That is 3 gantry axes + 6 arm joints = 9 axes per hand.

Both bridges share the same rails, so they can never pass each other:
the Handler always stays on the low-X side, the Cutter on the high-X side,
and their bridges must stay at least MIN_GAP apart.
"""
import numpy as np

from gantry.arm import Arm, wrap

# ---- cell layout (metres) ----
WORK_LENGTH = 12.0             # usable length along X
WIDTH = 3.0                    # rails are 3 m apart (Y from -1.5 to +1.5)
RAIL_Z = 3.4                   # height of the rails / bridges
BED_Z = 0.9                    # top of the beam supports (beam sits on this)
BEAM_Y = -0.5                  # centre line of the beam on the bed
OUTFEED_Y = 0.85               # where finished parts are put down
X_LIMITS = (-1.3, WORK_LENGTH + 1.3)   # rails run past both ends for parking
Y_LIMITS = (-1.4, 1.4)
Z_LIMITS = (1.25, 3.0)         # height of the arm base (bottom of the column)
Z_SAFE = 3.0                   # column fully up: safe to travel anywhere
MIN_GAP = 1.0                  # closest the two bridges may get (centre to centre)

# Gantry axis speeds (m/s) and acceleration (m/s^2)
AXIS_SPEED = np.array([1.0, 0.8, 0.5])
AXIS_ACCEL = 1.0

# Starting guesses (degrees, J1 is added on top) that lead to "elbow up" poses
# for an upside-down arm. Found once by a search over many starting poses.
ELBOW_UP_SEEDS = [(0, -90, -60, 0, 90, 0), (0, -90, -120, 90, 90, 0), (0, -90, -60, -90, -90, 0),
                  (0, -30, -120, 0, -90, 0), (0, -90, -60, 90, -90, 0)]
_PREFS = {}   # remembered comfortable poses, shared by every plan

# Arm mounted upside down: base X stays X, Y and Z flip. (This matrix is its own inverse.)
FLIP = np.diag([1.0, -1.0, -1.0])


class Hand:
    """One bridge + carriage + column + arm."""

    def __init__(self, name, arm, tool, color, park, payload_kg=0.0):
        self.name = name
        self.arm = arm
        self.tool = tool              # "torch" or "magnet"
        self.color = color
        self.park = np.array(park, dtype=float)   # gantry (x, y, z) when idle
        self.payload_kg = payload_kg

    # ---- coordinates ----
    @staticmethod
    def to_local(g, p, d=None):
        """World point (and direction) -> the arm's own base frame."""
        pl = FLIP @ (np.asarray(p) - g)
        return pl if d is None else (pl, FLIP @ np.asarray(d))

    def world_frames(self, g, q):
        B = np.eye(4)
        B[:3, :3] = FLIP
        B[:3, 3] = g
        return [B @ F for F in self.arm.frames(q)]

    def tip(self, g, q):
        p, z = self.arm.tip(q)
        return g + FLIP @ p, FLIP @ z

    # ---- solving ----
    def solve(self, g, p, d, seed):
        pl, dl = self.to_local(g, p, d)
        return self.arm.ik(pl, dl, seed)

    def preference(self, d, side):
        """A comfortable arm pose for pointing the tool along world direction `d`,
        with the column standing off to world direction `side` from the tool tip.

        "Comfortable" = the whole arm stays ABOVE the tool tip (elbow up, like a real
        ceiling-mounted robot), so it can't dip into the beam or the bed.
        Returns (offset, q): the tool tip sits at gantry + offset when the joints are q.
        Worked out once by trying a few reach/height combinations, then remembered.
        """
        key = (self.name, tuple(np.round(d, 3)), tuple(np.round(side, 3)))
        if key in _PREFS:
            return _PREFS[key]
        d = np.asarray(d, float) / np.linalg.norm(d)
        side = np.asarray(side, float) / np.linalg.norm(side)
        s = self.arm.reach
        best = None
        for r in (0.35, 0.45, 0.55):
            for depth in (0.25, 0.35, 0.45, 0.55):
                offset = -side * r * s + np.array([0, 0, -depth * s])  # tip relative to base
                pl, dl = self.to_local(np.zeros(3), offset, d)
                j1 = np.arctan2(pl[1], pl[0]) + np.pi      # base turned to face the target
                for seed in ELBOW_UP_SEEDS:
                    q, ep, ed = self.arm.ik(pl, dl, np.radians(seed) + [j1, 0, 0, 0, 0, 0], iterations=60)
                    if ep < 1e-4 and ed < 1e-3:
                        score = min(self.clearance(q), 0.2) - 0.01 * abs(depth - 0.4)
                        if best is None or score > best[0]:
                            best = (score, offset, wrap(q))
        if best is None:
            raise RuntimeError(f"{self.name}: no comfortable pose for direction {d}")
        _PREFS[key] = (best[1], best[2])
        return _PREFS[key]

    def clearance(self, q):
        """How far the lowest joint (shoulder to wrist) is above the tool tip, in metres."""
        z = [-F[2, 3] for F in self.arm.frames(q)]   # base frame is upside down
        return min(z[1:6]) - z[-1]

    def place(self, p, d, side):
        """Gantry position (x, y, z) that puts the tool comfortably on point p."""
        offset, q = self.preference(d, side)
        g = np.asarray(p) - offset
        lo = np.array([X_LIMITS[0], Y_LIMITS[0], Z_LIMITS[0]])
        hi = np.array([X_LIMITS[1], Y_LIMITS[1], Z_LIMITS[1]])
        return np.clip(g, lo, hi), q


def make_hands():
    """The two hands of the cell."""
    cutter = Hand("Cutter", Arm(scale=1.0, tool_length=0.30, joint_speed_deg=120),
                  tool="torch", color="#c0392b", park=[X_LIMITS[1] - 0.2, 0.9, Z_SAFE])
    handler = Hand("Handler", Arm(scale=1.3, tool_length=0.12, joint_speed_deg=90),
                   tool="magnet", color="#2471a3", park=[X_LIMITS[0] + 0.2, 0.9, Z_SAFE],
                   payload_kg=250.0)
    return cutter, handler


def move_time(g0, g1, q0, q1, joint_speed):
    """Time for a synchronised move: the slowest axis decides."""
    dist = np.abs(np.asarray(g1) - np.asarray(g0))
    t_axes = np.where(dist > AXIS_SPEED**2 / AXIS_ACCEL,
                      dist / AXIS_SPEED + AXIS_SPEED / AXIS_ACCEL,
                      2 * np.sqrt(dist / AXIS_ACCEL))
    t_joints = np.max(np.abs(np.asarray(q1) - np.asarray(q0))) / joint_speed * 1.5
    return float(max(np.max(t_axes), t_joints, 0.2))
