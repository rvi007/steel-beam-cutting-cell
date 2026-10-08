"""
The gantry cell: a 12 m or 20 m long (LENGTHS, set_length), 3 m wide work area with two overhead hands.

            Y (width, 3 m)
            ^
            |   outfeed table (finished parts)      y = +0.85
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
import json
import os

import numpy as np

from beamcell.arm import Arm, wrap
from beamcell.config import CONFIG, ROOT

LENGTHS = (12.0, 20.0)         # the machine sizes the software knows (work length along X, m)
CHOICE_FILE = os.path.join(ROOT, "config", "machine.json")   # the size picked on the screen (kept on this machine)

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

# ---- what holds the steel up: every loose piece must rest on one of these (gravity) ----
G = 9.81                       # m/s^2
ROLLER_R = 0.05                # bed rollers, top of each roller = BED_Z
ROLLER_X = [0.5 + i for i in range(12)]          # every 1 m; the bar ends overhang, so the trim falls clear
OUTFEED_DECK = (-0.3, WORK_LENGTH + 0.3, OUTFEED_Y - 0.45, OUTFEED_Y + 0.45)   # x0, x1, y0, y1; top = BED_Z
SCRAP_TRAY_Z = 0.10            # floor of the scrap tray under the bed (offcuts fall onto it)


def set_length(length_m):
    """Make the cell 12 m or 20 m long. Everything that depends on the length follows: the rails, the
    parking places, the rollers, the outfeed table (the planner, the bar check and the 3D view read them)."""
    global WORK_LENGTH, X_LIMITS, ROLLER_X, OUTFEED_DECK
    length_m = float(length_m)
    if length_m not in LENGTHS:
        raise ValueError(f"machine length must be one of {', '.join(f'{x:g} m' for x in LENGTHS)}")
    WORK_LENGTH = length_m
    X_LIMITS = (-1.3, WORK_LENGTH + 1.3)
    ROLLER_X = [0.5 + i for i in range(int(round(WORK_LENGTH)))]
    OUTFEED_DECK = (-0.3, WORK_LENGTH + 0.3, OUTFEED_Y - 0.45, OUTFEED_Y + 0.45)
    return WORK_LENGTH


def saved_length():
    """The size chosen on the screen (config/machine.json), else config/cell.toml [machine] length_m."""
    try:
        with open(CHOICE_FILE) as fh:
            return float(json.load(fh)["length_m"])
    except (OSError, ValueError, KeyError):
        return float(CONFIG.get("machine", {}).get("length_m", 12))


def choose_length(length_m):
    """Change the size and remember it for the next start."""
    set_length(length_m)
    os.makedirs(os.path.dirname(CHOICE_FILE), exist_ok=True)
    with open(CHOICE_FILE, "w") as fh:
        json.dump({"length_m": WORK_LENGTH}, fh)
    return WORK_LENGTH


def supported_on_rollers(x0, x1):
    """Does a loose piece lying from x0 to x1 (m) stay on the bed? It needs a roller on each side
    of its middle - one roller alone would let it tip over and fall into the scrap tray."""
    mid = (x0 + x1) / 2
    return any(x0 <= r < mid for r in ROLLER_X) and any(mid <= r <= x1 for r in ROLLER_X)


def fall_time(height):
    """Seconds for a piece to drop `height` metres (from rest, no air drag)."""
    return (2 * max(height, 0.0) / G) ** 0.5


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
    cutter = Hand("Cutter", Arm(scale=1.0, tool_length=0.40, joint_speed_deg=120),
                  tool="torch", color="#e8641b", park=[X_LIMITS[1] - 0.2, 0.9, Z_SAFE])
    handler = Hand("Handler", Arm(scale=1.3, tool_length=0.12, joint_speed_deg=90),
                   tool="magnet", color="#1f6fb2", park=[X_LIMITS[0] + 0.2, 0.9, Z_SAFE],
                   payload_kg=500.0)
    return cutter, handler


def move_time(g0, g1, q0, q1, joint_speed):
    """Time for a synchronised move: the slowest axis decides."""
    dist = np.abs(np.asarray(g1) - np.asarray(g0))
    t_axes = np.where(dist > AXIS_SPEED**2 / AXIS_ACCEL,
                      dist / AXIS_SPEED + AXIS_SPEED / AXIS_ACCEL,
                      2 * np.sqrt(dist / AXIS_ACCEL))
    t_joints = np.max(np.abs(np.asarray(q1) - np.asarray(q0))) / joint_speed * 1.5
    return float(max(np.max(t_axes), t_joints, 0.2))


def describe():
    """Everything the 3D view needs to draw and move the machine (sent to the browser)."""
    out = {"work_length": WORK_LENGTH, "lengths": LENGTHS, "width": WIDTH, "rail_z": RAIL_Z, "bed_z": BED_Z, "beam_y": BEAM_Y,
           "outfeed_y": OUTFEED_Y, "x_limits": X_LIMITS, "z_safe": Z_SAFE, "min_gap": MIN_GAP, "hands": {},
           "roller_x": ROLLER_X, "roller_r": ROLLER_R, "outfeed_deck": OUTFEED_DECK, "scrap_tray_z": SCRAP_TRAY_Z, "g": G}
    for hand in make_hands():
        a = hand.arm
        out["hands"][hand.name.lower()] = {"name": hand.name, "tool": hand.tool, "color": hand.color,
                                            "a": a.a.tolist(), "d": a.d.tolist(), "alpha": a.alpha.tolist(),
                                            "tool_length": a.tool_length, "payload_kg": hand.payload_kg,
                                            "park": hand.park.tolist(),
                                            "rest_q": hand.preference([0, 0, -1], [1, 0, 0] if hand.tool == "torch"
                                                                      else [-1, 0, 0])[1].tolist()}
    return out


try:
    set_length(saved_length())
except ValueError:
    set_length(12)
