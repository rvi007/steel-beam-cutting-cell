"""
Headless test for ik_target.py - no window, no Arduino needed.

Run:   python3 test_ik_target.py

It loads ik_target.py without opening a window, then moves the sliders in code:
  1. The cases that used to go wrong (big jumps, unreachable targets).
  2. 300 random target jumps inside the reachable zone
     (reach 0.25-0.75 m, height 0-0.5 m), with an unreachable jump every 10th time.
Pass = 0 failures (error >= 2 mm) and 0 flips (base more than 45 deg off the target).
"""
import sys

import matplotlib
matplotlib.use("Agg")                    # draw off-screen
matplotlib.use = lambda *args, **kw: None  # stop ik_target.py switching to TkAgg
import numpy as np

src = open("ik_target.py").read().split("# Main loop")[0]
src = src.replace("arduino = find_arduino()", "arduino = None")
ik = {"__name__": "ik_test"}
exec(src, ik)
angle, reach, height, state = ik["angle"], ik["reach"], ik["height"], ik["state"]


def go(a, r, h):
    """Move the target like the sliders would. Returns (error mm, J1 offset deg)."""
    angle.set_val(a)
    reach.set_val(r)
    height.set_val(h)
    return state["err"] * 1000, np.degrees(state["q"][0]) - a


print("Cases that used to go wrong (angle, reach, height):")
for case in [(0, .5, .2), (60, .5, .2), (-90, .6, .1), (30, .95, .2), (30, .4, .6),
             (-90, .6, .1), (90, .3, 0.0), (-45, .75, .5)]:
    err, offset = go(*case)
    note = "  (unreachable on purpose)" if case[1] > 0.85 else ""
    print(f"  {str(case):<18} error {err:7.2f} mm   J1 offset {offset:+6.1f}°{note}")

rng = np.random.default_rng(0)
fails = flips = 0
worst = 0.0
for i in range(300):
    if i % 10 == 0:
        go(rng.uniform(-90, 90), 0.95, rng.uniform(0, 0.7))  # unreachable first
    a, r, h = rng.uniform(-90, 90), rng.uniform(0.25, 0.75), rng.uniform(0, 0.5)
    err, offset = go(a, r, h)
    worst = max(worst, err)
    if err >= 2:
        fails += 1
        print(f"  FAIL  target ({a:.0f}, {r:.2f}, {h:.2f})  error {err:.1f} mm")
    if abs(offset) > 45:
        flips += 1
        print(f"  FLIP  target ({a:.0f}, {r:.2f}, {h:.2f})  J1 offset {offset:+.1f}°")

print(f"\n300 random jumps: {fails} failures, {flips} flips, worst error {worst:.2f} mm")
if fails or flips:
    print("FAIL")
    sys.exit(1)
print("PASS")
