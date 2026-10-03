# Robot Arm Learning Project - context for Claude Code

The user is learning robotics step by step: a simulated 6-axis arm (UR5-like geometry)
plus a real hardware "joint" (one servo + one potentiometer on an Arduino UNO),
running on an NVIDIA Jetson Orin (Linux, aarch64). Keep explanations simple and
beginner-friendly; lessons are numbered and build on each other.

Full Jetson hardware/software specs and memory limits: see `JETSON_SPECS.md`.

## Where code runs
- **Jetson (local):** the only place the Arduino, servo, knob and the 3D windows exist.
  All hardware tests must be done there.
- **Cloud session (GitHub repo):** no Arduino, no display. Use it for writing/refactoring
  code and headless tests only. Push changes; the user pulls on the Jetson to try them.

## Constraints
- Fully offline libraries only: numpy, matplotlib (TkAgg), scipy, pyserial. No pip installs
  (Jetson is on a mobile hotspot).
- GUI scripts call `matplotlib.use("TkAgg")`. To test headless: set Agg, monkeypatch
  `matplotlib.use` to a no-op, exec the script source up to the `# Main loop` marker with
  `arduino = None`, then drive sliders/buttons by calling their callbacks / `set_val`.

## Files
| File | What it is |
|---|---|
| `robot.py` | Shared model: DH params, `forward_kinematics`, `inverse_kinematics` (damped least squares, numerical Jacobian, optional tool-pointing-down), drawing helpers |
| `lesson01_joints.py` | Lesson 1: 6 sliders, joint control |
| `sim.py` | `Robot` class: `move_joints`, `move_joint`, `home`, `tool_position` with eased animation |
| `my_program.py` | User's playground using `sim.Robot` |
| `exercises.py` / `solutions.py` | 8 auto-checked exercises. `python3 exercises.py all --quick --solution` must print 8/8 |
| `digital_twin.py` | Real servo = J1. Slider -> servo, knob -> 3D robot + servo. **Tested working on hardware.** |
| `teach_replay.py` | Record knob waypoints, replay with eased trajectories, speed slider, loop, saves `waypoints.json`. Logic tested headless; launched on hardware OK. |
| `ik_target.py` | Inverse kinematics: knob swings a target around the base, IK solves all 6 joints (tool down), servo follows J1, clamps at ±90° and shows "SERVO LIMIT". Tested headless; hardware test pending. |
| `test_ik_target.py` | Headless test for `ik_target.py` (no window/Arduino). Must print PASS. |
| `test_scripts_load.py` | Smoke test: each window script loads headless up to its main loop. Must print PASS. |
| `.github/workflows/tests.yml` | CI on every push, twice: with the Jetson's library versions (Python 3.10, numpy 1.21.5, matplotlib 3.5.1) and with the latest. Runs py_compile, all tests, exercises 8/8, and compiles the Arduino sketch for the UNO. Keep it green. |
| `gantry_cell.py` + `gantry/` | **Big project**: 12 m beam-cutting gantry, two 9-axis hands (Cutter = plasma, Handler = magnet). Layout editor, planner, collision check, solid 3D view with blitting. Full design in `GANTRY.md`. |
| `test_gantry.py` | Headless tests for the gantry (IK, every profile, random jobs, rules, app clicks). Must print PASS. |
| `arduino/servo_joint/servo_joint.ino` | Servo pin 9, knob A0. Serial 115200. Orin->Arduino `S<0..180>\n`; Arduino->Orin `K<0..180>\n` every 50 ms (smoothed) |

Angle mapping everywhere: robot J1 -90..+90 deg  <->  servo 0..180 deg.
Target angle 0 = straight out along -X (where the arm points at J1 = 0).

## Current status / next task
- `ik_target.py` solve() fallback: tested headless and on the Jetson (`test_ik_target.py` PASS).
  Hardware check of the servo still to report back.
- **Gantry cell** (`gantry_cell.py`, `gantry/`, `GANTRY.md`): working in simulation. Demo job
  plans on all 4 profiles at 12 m and 6 m, random jobs plan with no collisions, the bridges
  stay >= 1 m apart. About 80 ms per frame on the cloud runner thanks to blitting, so expect
  roughly 6-10 fps on the Jetson. Not yet run on the Jetson screen.
- Gantry design notes: arms hang upside down (`FLIP`), elbow-up poses come from
  `Hand.preference` (seeded by `ELBOW_UP_SEEDS`, cached in `_PREFS`); the Cutter's torch is
  300 mm long so the wrist clears a 300 mm HEB flange on the 45 deg bottom-flange cuts;
  `Plan._commit` checks the bridge gap against everything the other hand has planned from
  then on. Keep `test_gantry.py` green; `gantry/check.py` must find 0 collisions.
- Next ideas for the gantry are in GANTRY.md section 6 (DSTV/NC1 import first).

## Roadmap (README.md)
1 joints (done), 2 forward kinematics, 3 inverse kinematics (ik_target.py), 4 joint-space
trajectories (teach_replay.py covers basics), 5 Cartesian straight-line motion (Jacobian),
6 pick-and-place, 7 gantry cell (the user's "big project"). Ideas the user was offered: second servo for J2, PID/velocity control
with live graphs.

## Jetson setup notes
- User `ravi` was added to `dialout` for `/dev/ttyACM0`. A shell started before that needs
  `sg dialout -c "python3 script.py"` (or log out/in).
- `arduino-cli` is at `~/.local/bin/arduino-cli`; board FQBN `arduino:avr:uno`.
- Only one program can hold the serial port at a time - close one window before opening another.
