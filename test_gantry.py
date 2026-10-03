"""
Headless tests for the gantry cell (gantry/ + gantry_cell.py) - no window, no Arduino.

Run:   python3 test_gantry.py           (about 2 minutes)
       python3 test_gantry.py --quick   (fewer random jobs)

Checks:
  1. The arm's inverse kinematics reaches targets with the tool pointing any way.
  2. The demo job on every profile, 12 m and 6 m: plans with no warnings, the bridges
     never get closer than MIN_GAP, the arms never touch the steel, every feature gets
     cut and every part ends up on the outfeed rack.
  3. Random jobs: same safety checks.
  4. Bad features are refused (too small, too close to the web, a cut through a hole...).
  5. Jobs save and load.
  6. The app itself: click to add features, plan, run, delete, save, load.
"""
import os
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")                    # draw off-screen
matplotlib.use = lambda *args, **kw: None  # stop gantry_cell.py switching to TkAgg
import matplotlib.pyplot as plt
import numpy as np

from gantry.arm import Arm
from gantry.beam import PROFILES, Job, demo_job
from gantry.check import check_plan
from gantry.machine import MIN_GAP, OUTFEED_Y, BEAM_Y
from gantry.planner import Plan
from gantry.randomjob import random_job

QUICK = "--quick" in sys.argv
failures = []


def check(ok, what):
    print(f"  {'OK  ' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def plan_is_safe(job, label, expect_carried=True):
    plan = Plan(job).build()
    hits = check_plan(plan, step=0.3)
    warnings = [w for w in plan.warnings if "too heavy" not in w]
    gap = plan.min_gap()
    valid = [i for i, f in enumerate(job.features) if not job.check(f)]
    not_done = [i for i in valid if i not in plan.feature_done]
    ok = not hits and not warnings and gap >= MIN_GAP - 1e-9 and not not_done
    detail = f"{plan.summary().splitlines()[0]}, closest bridges {gap:.2f} m"
    if hits:
        detail += f", {len(hits)} COLLISIONS e.g. {hits[0]}"
    if warnings:
        detail += f", warnings: {warnings[:2]}"
    if not_done:
        detail += f", features never cut: {not_done}"
    check(ok, f"{label}: {detail}")
    if expect_carried:
        heavy = {i for i in range(len(job.parts())) if job.weight(i) > plan.handler.payload_kg}
        carried = {c["part"] for c in plan.carries}
        last = len(job.parts()) - 1
        want = {i for i in range(len(job.parts())) if i not in heavy and i != last}
        on_rack = all(abs(BEAM_Y + plan.part_offset(i, plan.duration)[1] - OUTFEED_Y) < 1e-6 for i in carried)
        check(want <= carried and on_rack, f"{label}: parts {sorted(p + 1 for p in carried)} carried "
                                           f"to the outfeed rack")
    return plan


print("1. Arm inverse kinematics (any tool direction)")
arm = Arm(scale=1.0, tool_length=0.3)
rng = np.random.default_rng(1)
worst, fails = 0.0, 0
q_seed = np.radians([0, -90, -60, 0, 90, 0])
for _ in range(200):                     # start up to 23 deg away on every joint
    q_true = q_seed + rng.uniform(-0.4, 0.4, 6)
    p, d = arm.tip(q_true)
    q, ep, ed = arm.ik(p, d, q_seed, iterations=150)
    worst = max(worst, ep)
    fails += ep > 1e-3 or ed > 1e-2
check(fails == 0, f"200 random poses: {fails} not solved, worst error {worst * 1000:.2f} mm")

print("2. Demo job on every profile, 12 m and 6 m")
for profile in PROFILES:
    for length in (12.0, 6.0):
        job = demo_job(profile, length)
        check(not job.problems(), f"{profile} {length:.0f} m demo has no problems {job.problems()[:2]}")
        plan_is_safe(job, f"{profile} {length:.0f} m")

print("3. Random jobs")
for seed in range(4 if QUICK else 12):
    job = random_job(seed)
    plan_is_safe(job, f"random job {seed} ({job.profile}, {job.length:.0f} m, {len(job.features)} features)",
                 expect_carried=False)

print("4. Bad features are refused")
job = demo_job("IPE300")
bad = {
    "hole too small for plasma": {"type": "hole", "face": "top", "x": 6.5, "v": 0.045, "d": 0.008},
    "hole on top of the web": {"type": "hole", "face": "top", "x": 6.5, "v": 0.0, "d": 0.02},
    "hole past the flange edge": {"type": "hole", "face": "top", "x": 6.5, "v": 0.07, "d": 0.02},
    "web hole into a flange": {"type": "hole", "face": "web", "x": 6.5, "v": 0.01, "d": 0.02},
    "cut through a hole": {"type": "cut", "x": 1.2},
    "part shorter than 150 mm": {"type": "cut", "x": 2.45},
    "notch deeper than the web": {"type": "notch", "x": 2.4, "side": 1, "w": 0.1, "depth": 0.29},
    "outside the beam": {"type": "hole", "face": "web", "x": 12.5, "v": 0.15, "d": 0.02},
}
for name, f in bad.items():
    check(bool(job.check(f)), f"{name}: '{job.check(f)}'")
check(not job.check({"type": "hole", "face": "top", "x": 6.5, "v": 0.045, "d": 0.02}), "a good hole is accepted")

print("5. Save and load")
again = Job.from_json(job.to_json())
check(again.profile == job.profile and again.length == job.length and again.features == job.features,
      "job survives JSON round trip")

print("6. The app (clicks, plan, run)")
plt.pause = lambda *a, **k: None
src = open("gantry_cell.py").read().split("# Main loop")[0]
src = src.replace("arduino = find_arduino()", "arduino = None")
app = {"__name__": "gantry_test", "__file__": os.path.abspath("gantry_cell.py")}
exec(compile(src, "gantry_cell.py", "exec"), app)
state = app["state"]
tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
tmp.close()
app["JOB_FILE"] = tmp.name


class Click:
    def __init__(self, axes, x, y, button=1):
        self.inaxes, self.xdata, self.ydata, self.button = axes, x, y, button


app["set_job"](Job("IPE300", 12.0), "empty")
n0 = len(state["job"].features)
app["tool_radio"].set_active(0)                      # Hole
app["on_click"](Click(app["ax_top"], 3.0, 45.0))      # top flange, 45 mm out
app["on_click"](Click(app["ax_web"], 3.5, 150.0))     # web, 150 mm up
app["on_click"](Click(app["ax_top"], 4.0, 0.0))       # on the web -> refused
app["tool_radio"].set_active(3)                      # Cut
app["on_click"](Click(app["ax_web"], 5.0, 100.0))
app["tool_radio"].set_active(2)                      # Notch 100 mm long, 45 mm deep,
app["size"].set_val(100)                             # near the cut at 5.0, on its right
app["extra"].set_val(45)
app["on_click"](Click(app["ax_web"], 5.05, 280.0))
feats = state["job"].features
check(len(feats) - n0 == 4, f"clicks added 4 features, refused 1: {[f['type'] for f in feats]}")
check(state["msg_bad"] is False, f"last message: {state['message']}")
notch = [f for f in feats if f["type"] == "notch"]
check(len(notch) == 1 and notch[0]["x"] == 5.0 and notch[0]["side"] == 1, "notch snapped to the cut, on the right")
app["tool_radio"].set_active(4)                      # Delete the web hole
app["on_click"](Click(app["ax_web"], 3.5, 150.0))
check(len(state["job"].features) - n0 == 3, "delete removed one feature")

app["on_plan"]()
plan = state["plan"]
check(plan is not None and state["checked"] == "collision check: OK", f"PLAN button: {state['message']}")
app["on_run"]()
check(state["running"], "RUN starts playback")
for view in app["VIEWS"]:
    app["on_view"](view)
    for k in range(3):
        state["last_real"] -= 1.0                       # pretend a second went by
        app["tick"]()
check(state["t"] > 0, f"time advanced to {state['t']:.1f} s while running")
app["timeline"].set_val(plan.duration)
app["frame"]()
check(state["t"] == plan.duration, "time slider jumps to the end")
app["on_save"]()
app["set_job"](demo_job(), "demo")
app["on_load"]()
check(len(state["job"].features) - n0 == 3, "Save then Load gives the same job back")
os.unlink(tmp.name)

print()
if failures:
    print(f"FAIL ({len(failures)} problem(s))")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("PASS")
