# 6-Axis Robot Arm - Learn Step by Step

Fully offline: uses only numpy, matplotlib and scipy (already installed).
No downloads needed, so it's safe on a mobile hotspot.

Robot: 6 joints with geometry like a Universal Robots UR5 (reach about 0.85 m).

## Run a lesson
```
cd ~/robot_arm
python3 lesson01_joints.py
```

## Tests
GitHub runs these automatically on every push (Actions tab). You can also run them yourself:
```
python3 test_scripts_load.py                  # every window script starts
python3 exercises.py all --quick --solution   # must say 8/8
python3 test_ik_target.py                     # inverse kinematics, must say PASS
python3 test_gantry.py --quick                # the gantry cell, must say PASS
```

## Big project: the gantry cell
```
python3 gantry_cell.py
```
A 12 m steel-beam cutting cell with two robot hands on an overhead gantry: a plasma
**Cutter** and a magnet **Handler**. Click on the beam layout to place holes, slots,
notches and cuts, press PLAN, then RUN. The full plan and how it works: [GANTRY.md](GANTRY.md).

## Roadmap
| # | Lesson | You learn |
|---|--------|-----------|
| 1 | Joint control (sliders) | What each of the 6 axes does |
| 2 | Forward kinematics | How joint angles give the tool position (DH transforms) |
| 3 | Inverse kinematics | Ask for a position, robot computes joint angles |
| 4 | Joint-space motion | Smooth moves between poses (trajectories) |
| 5 | Cartesian straight-line motion | Moving the tool along a straight line (Jacobian) |
| 6 | Pick-and-place program | Chaining moves into a real robot task |
| 7 | Gantry cell (`gantry_cell.py`) | Two 9-axis hands, path planning, collision avoidance, a real process |

## Files
- `robot.py` - the robot model (DH parameters, kinematics, drawing). Shared by all lessons.
- `lessonNN_*.py` - one file per lesson.
- `exercises.py` - 8 practice exercises with automatic checking (`python3 exercises.py 1`, or `all --quick`).
- `solutions.py` - model answers (`python3 exercises.py 1 --solution`).
