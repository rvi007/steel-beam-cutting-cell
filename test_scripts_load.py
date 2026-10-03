"""
Smoke test: every window script still starts without errors.

Run:   python3 test_scripts_load.py

Opens each script off-screen with no Arduino, runs it up to the point where it
would sit waiting for you (the main loop / plt.show()), then closes it.
Catches typos and broken imports before you try it on the Jetson.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")                    # draw off-screen
matplotlib.use = lambda *args, **kw: None  # stop the scripts switching to TkAgg
import matplotlib.pyplot as plt

SCRIPTS = {  # script -> the line where it starts waiting for the user
    "lesson01_joints.py": "plt.show()",
    "digital_twin.py": "# Main loop",
    "teach_replay.py": "# Main loop",
    "ik_target.py": "# Main loop",
}

failed = []
for name, stop_at in SCRIPTS.items():
    src = open(name).read()
    src = src.split(stop_at)[0].replace("arduino = find_arduino()", "arduino = None")
    try:
        exec(compile(src, name, "exec"), {"__name__": "smoke_test", "__file__": os.path.abspath(name)})
        print(f"  OK    {name}")
    except Exception as e:
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        failed.append(name)
    plt.close("all")

if failed:
    print("FAIL")
    sys.exit(1)
print("PASS")
