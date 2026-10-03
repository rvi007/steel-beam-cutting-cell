# Robot Arm Learning Project - context for Claude Code

The user is learning robotics step by step: a simulated 6-axis arm (UR5-like geometry)
plus a real hardware "joint" (one servo + one potentiometer on an Arduino UNO),
running on an NVIDIA Jetson Orin (Linux, aarch64). Keep explanations simple and
beginner-friendly; lessons are numbered and build on each other.

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
| `arduino/servo_joint/servo_joint.ino` | Servo pin 9, knob A0. Serial 115200. Orin->Arduino `S<0..180>\n`; Arduino->Orin `K<0..180>\n` every 50 ms (smoothed) |
| `arduino/encoder_test/encoder_test.ino` | Rotary encoder wiring test (CLK 2, DT 3, SW 4) |

Angle mapping everywhere: robot J1 -90..+90 deg  <->  servo 0..180 deg.
Target angle 0 = straight out along -X (where the arm points at J1 = 0).

## Current status / next task
`ik_target.py` has a `solve()` fallback: warm-start IK from the previous answer, and
if it fails (error >= 2 mm) or the base flips (> 45 deg from the aimed guess), re-solve
from `fresh_seed(target)` (J1 aimed at target minus asin(0.10915 / r) shoulder offset).
**Tested headless (cloud):** `python3 test_ik_target.py` -> 300 random jumps, 0 failures,
0 flips, worst 0.10 mm. The old bad cases are fixed: (-90, 0.6, 0.1) now 0.0 mm (was 740 mm),
unreachable (30, 0.95, 0.2) stretches toward the target with J1 offset -7 deg (was a
-174 deg flip). `exercises.py all --quick --solution` still 8/8.
Next: hardware test on the Jetson (knob -> target, servo follows J1, SERVO LIMIT at ±90).

## Roadmap (README.md)
1 joints (done), 2 forward kinematics, 3 inverse kinematics (ik_target.py), 4 joint-space
trajectories (teach_replay.py covers basics), 5 Cartesian straight-line motion (Jacobian),
6 pick-and-place. Ideas the user was offered: second servo for J2, PID/velocity control
with live graphs.

## Jetson setup notes
- User `ravi` was added to `dialout` for `/dev/ttyACM0`. A shell started before that needs
  `sg dialout -c "python3 script.py"` (or log out/in).
- `arduino-cli` is at `~/.local/bin/arduino-cli`; board FQBN `arduino:avr:uno`.
- Only one program can hold the serial port at a time - close one window before opening another.
