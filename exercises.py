"""
ROBOT ARM SIMULATOR - EXERCISES (with automatic checking)

Write your moves inside each exercise function below, then run:

    python3 exercises.py 1            run exercise 1 in the 3D window, then check it
    python3 exercises.py 1 --quick    check only, no window (instant)
    python3 exercises.py all --quick  check every exercise
    python3 exercises.py 1 --solution watch the model answer (from solutions.py)

Commands (same as my_program.py):
    bot.move_joints([j1, j2, j3, j4, j5, j6])   all 6 joints, degrees
    bot.move_joint(number, angle)               one joint (1..6)
    bot.home()                                  back to [0, -90, 0, -90, 0, 0]
    bot.tool_position()                         [x, y, z] in metres

Tip: use lesson01_joints.py (the sliders) to find good angles, then type them here.
"""
import sys

import numpy as np

import robot

# Targets used by the exercises (metres).
TARGET_4 = np.array([-0.385, -0.349, 0.229])
PICK_A = np.array([-0.352, -0.507, 0.123])
PLACE_B = np.array([-0.507, 0.352, 0.123])
CLOSE_ENOUGH = 0.03  # 3 cm


# ======================================================================
# EXERCISES - write your code where it says "pass"
# ======================================================================

def ex1(bot):
    """BASE SPIN
    Rotate the base (J1) to -90°, then to +90°, then back to 0°.
    """
    pass


def ex2(bot):
    """REACH FAR
    Stretch the arm out so the tool is at least 0.85 m from the base,
    measured horizontally (ignore height).  Hint: the shoulder is J2.
    """
    pass


def ex3(bot):
    """LOW BUT SAFE
    Bring the tool tip down so its Z is below 0.20 m but above 0.02 m
    (don't crash into the floor!).
    """
    pass


def ex4(bot):
    """HIT THE TARGET
    Move the tool to within 3 cm of  X=-0.385  Y=-0.349  Z=+0.229.
    Use the lesson 1 sliders to search - this is "inverse kinematics by hand".
    """
    pass


def ex5(bot):
    """LIGHTHOUSE SWEEP
    With the arm reaching out (tool at least 0.5 m from the base horizontally),
    swing the base from -180° all the way to +180°.  The orange trail should
    draw a full circle.
    """
    pass


def ex6(bot):
    """SPIN THE TOOL, NOT THE TIP
    In ONE move, turn the tool's orientation by at least 170° while the tip
    moves less than 5 mm.  Which single joint can do that?
    """
    pass


def ex7(bot):
    """CLOCK FACE  (use a for loop)
    Stop the base at 12 positions like the hours on a clock:
    0°, 30°, 60°, ... 330°  ->  but J1 is limited to ±180°, so use
    -180°, -150°, ... 150° instead.  Use a loop, not 12 lines!
    """
    pass


def ex8(bot):
    """PICK AND PLACE
    1. Go to PICK_A  (within 3 cm of X=-0.352 Y=-0.507 Z=+0.123)  - pick the part
    2. Lift the tool above Z = 0.30 m                               - safe travel height
    3. Go to PLACE_B (within 3 cm of X=-0.507 Y=+0.352 Z=+0.123)  - place the part
    4. Return home.
    Hint: PLACE_B is PICK_A mirrored - try changing only J1.
    """
    pass


# ======================================================================
# CHECKERS - you don't need to edit below this line
# ======================================================================

def tool_frame(joints_deg):
    return robot.forward_kinematics(np.radians(joints_deg))[-1]


def horiz(p):
    return float(np.hypot(p[0], p[1]))


def check1(h):
    j1 = [w[0] for w in h]
    seq = []
    for target in (-90, 90, 0):
        start = seq[-1] + 1 if seq else 0
        hit = next((k for k in range(start, len(j1)) if abs(j1[k] - target) < 1), None)
        if hit is None:
            return False, f"J1 never reached {target}° (in order -90, +90, 0)."
        seq.append(hit)
    return True, "Base went -90 -> +90 -> 0."


def check2(h):
    best = max(horiz(tool_frame(w)[:3, 3]) for w in h)
    return best >= 0.85, f"Furthest horizontal reach: {best:.3f} m (need >= 0.85)."


def check3(h):
    zs = [tool_frame(w)[2, 3] for w in h]
    if min(zs) <= 0.02:
        return False, f"Tool went down to Z={min(zs):.3f} m - that's into the floor!"
    ok = any(z < 0.20 for z in zs)
    return ok, f"Lowest Z reached: {min(zs):.3f} m (need 0.02 < Z < 0.20)."


def check4(h):
    d = min(np.linalg.norm(tool_frame(w)[:3, 3] - TARGET_4) for w in h)
    return d <= CLOSE_ENOUGH, f"Closest to target: {d * 100:.1f} cm (need <= 3 cm)."


def check5(h):
    extended = [w for w in h if horiz(tool_frame(w)[:3, 3]) >= 0.5]
    lo = any(w[0] <= -179 for w in extended)
    hi = any(w[0] >= 179 for w in extended)
    for a, b in zip(h, h[1:]):
        if a[0] <= -179 and b[0] >= 179 and horiz(tool_frame(a)[:3, 3]) >= 0.5:
            return True, "Full sweep -180° -> +180° with the arm reaching out."
    return False, (f"Need a move from J1=-180 to J1=+180 with reach >= 0.5 m "
                   f"(reached -180 extended: {lo}, +180 extended: {hi}).")


def check6(h):
    for a, b in zip(h, h[1:]):
        Ta, Tb = tool_frame(a), tool_frame(b)
        moved = np.linalg.norm(Tb[:3, 3] - Ta[:3, 3])
        cos = (np.trace(Ta[:3, :3].T @ Tb[:3, :3]) - 1) / 2
        turn = np.degrees(np.arccos(np.clip(cos, -1, 1)))
        if turn >= 170 and moved < 0.005:
            return True, f"Tool turned {turn:.0f}° while the tip moved {moved * 1000:.1f} mm."
    return False, "No single move turned the tool >= 170° with the tip moving < 5 mm."


def check7(h):
    needed = set(range(-180, 180, 30))
    got = {int(round(w[0])) for w in h} & needed
    missing = sorted(needed - got)
    return not missing, ("All 12 clock positions visited." if not missing
                         else f"Missing J1 stops: {missing}")


def check8(h):
    pos = [tool_frame(w)[:3, 3] for w in h]
    a = next((k for k, p in enumerate(pos) if np.linalg.norm(p - PICK_A) <= CLOSE_ENOUGH), None)
    if a is None:
        return False, "Never reached PICK_A."
    b = next((k for k in range(a + 1, len(pos))
              if np.linalg.norm(pos[k] - PLACE_B) <= CLOSE_ENOUGH), None)
    if b is None:
        return False, "Reached PICK_A, but never reached PLACE_B after it."
    if not any(p[2] > 0.30 for p in pos[a:b]):
        return False, "Went from A to B without lifting above Z=0.30 m - you'd hit something!"
    if np.max(np.abs(np.array(h[-1]) - [0, -90, 0, -90, 0, 0])) > 1:
        return False, "Placed the part, but didn't return home at the end."
    return True, "Picked at A, lifted, placed at B, returned home."


EXERCISES = {n: (globals()[f"ex{n}"], globals()[f"check{n}"]) for n in range(1, 9)}


def make_bot(quick):
    """A robot that remembers every pose it stops at, so we can check your work."""
    if quick:
        class QuickBot:  # same commands, no window, instant
            speed = 60

            def __init__(self):
                self.joints_deg = np.array([0, -90, 0, -90, 0, 0], dtype=float)
                self.history = [self.joints_deg.tolist()]

            def move_joints(self, target_deg, speed=None):
                target = np.array(target_deg, dtype=float)
                if target.shape != (6,):
                    raise ValueError("move_joints needs exactly 6 angles")
                for i, (lo, hi) in enumerate(robot.JOINT_LIMITS_DEG):
                    if not lo <= target[i] <= hi:
                        raise ValueError(f"{robot.JOINT_NAMES[i]} = {target[i]}° is outside [{lo}, {hi}]")
                self.joints_deg = target
                self.history.append(target.tolist())

            def move_joint(self, n, angle, speed=None):
                t = self.joints_deg.copy()
                t[n - 1] = angle
                self.move_joints(t)

            def home(self):
                self.move_joints([0, -90, 0, -90, 0, 0])

            def tool_position(self):
                return np.round(tool_frame(self.joints_deg)[:3, 3], 3).tolist()

            def wait(self, s): pass
            def clear_trail(self): pass
            def done(self): pass

        return QuickBot()

    from sim import Robot

    class RecordingBot(Robot):
        def __init__(self):
            super().__init__()
            self.history = [self.joints_deg.tolist()]

        def move_joints(self, target_deg, speed=None):
            super().move_joints(target_deg, speed)
            self.history.append(self.joints_deg.tolist())

    return RecordingBot()


def run(n, quick, solution):
    func, check = EXERCISES[n]
    if solution:
        import solutions
        func = getattr(solutions, f"ex{n}")
    print(f"\n=== Exercise {n}: {func.__doc__.strip().splitlines()[0]} ===")
    bot = make_bot(quick)
    func(bot)
    if len(bot.history) == 1:
        print("  NOT STARTED - write your code in ex%d() in exercises.py" % n)
        ok = False
    else:
        ok, msg = check(bot.history)
        print(("  PASS  " if ok else "  TRY AGAIN  ") + msg)
    if not quick:
        bot.done()
    return ok


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quick = "--quick" in sys.argv
    solution = "--solution" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(0)
    nums = list(EXERCISES) if args[0] == "all" else [int(args[0])]
    if len(nums) > 1 and not quick:
        print("Tip: use 'all --quick' to check everything without opening windows.")
    passed = sum(run(n, quick, solution) for n in nums)
    if len(nums) > 1:
        print(f"\nScore: {passed}/{len(nums)}")
