# Gantry cell - two-handed robot for structural steel

A simulated beam-processing cell: a 12 m overhead gantry with **two robot hands** that
cut holes, slots, notches (copes) and cut-to-length on I/H beams, and move the finished
parts out of the way. Built on the same kinematics as the earlier lessons
(`robot.py`, `ik_target.py`), scaled up to a real machine.

```
python3 gantry_cell.py      # the interactive cell
python3 test_gantry.py      # headless tests (about 2 minutes, or --quick)
```

## 1. The machine

```
   Y (width 3 m)
   ^      rails at 3.4 m on yellow posts, one at each side
   |  ==================================================================
   |   outfeed rack (green)   y = +0.85   finished parts go here
   |
   |   beam on bed rollers    y = -0.50   12 m stock, web standing up
   |  ==================================================================
   +----------------------------------------------------------------------> X (12 m work area)
        HANDLER bridge (blue) ->                     <- CUTTER bridge (red)
        parks at x = -1.1                                parks at x = 13.1
```

| | Cutter (red) | Handler (blue) |
|---|---|---|
| Job | plasma torch: holes, slots, notches, cut to length | magnet gripper: holds parts, carries them to the outfeed |
| Gantry axes | X bridge 1.0 m/s, Y carriage 0.8 m/s, Z column 0.5 m/s | same |
| Arm | 6 axes, UR5 geometry (0.85 m reach), hung upside down | 6 axes, 1.3x bigger (industrial size) |
| Tool | 300 mm torch body (long, to reach under the flange) | 120 mm stem + magnet pad, 250 kg payload |
| Total | **9 axes** | **9 axes** |

Both bridges share the same rails, so they can never pass each other. The Handler always
works on the low-X side and the Cutter on the high-X side, and the planner keeps the bridges
at least **1.0 m** apart (centre to centre) at every moment.

Both arms work **elbow up**, like real ceiling-mounted robots: the whole arm stays above the
tool tip so it can't dip into the beam or the bed. The planner picks these poses itself
(`Hand.preference` in `gantry/machine.py`).

## 2. What it can cut

Profiles: **IPE200, IPE300, HEA200, HEB300** (add more in `PROFILES`, `gantry/beam.py`).
Stock: **12 m or 6 m**.

| Feature | Where | How the torch does it |
|---|---|---|
| Hole | top flange or web | pierce in the middle, lead in to the edge, once round + 17 deg overlap |
| Slot | top flange or web | same, around a stadium shape |
| Notch (cope) | at a part end | cross-cut the top flange, then down the web and along, with a 12 mm radius corner |
| Cut to length | anywhere | full profile: top flange (torch down), web (torch from the side), bottom flange in two halves with the torch tilted 45 deg, from each side |

Rules the editor enforces (`Job.check`):
- plasma holes at least 1.2x the plate thickness, and at least 10 mm
- flange holes clear of the web root (15 mm) and the flange edge (8 mm)
- web holes clear of both flanges
- parts at least 150 mm long; a cut may not go through a hole, slot or notch
- notch depth between the flanges

Cutting speeds follow typical 130 A plasma values: 50 mm/s up to 6 mm thick, down to
16 mm/s over 15 mm. Each pierce takes 0.6 s.

## 3. How a job runs

The planner (`gantry/planner.py`) works through the beam part by part, from X = 0:

1. **Cutter** cuts the part's holes and slots (all top-flange work first, then the web),
   then its notches.
2. **Cutter** moves to the cut-off and **waits**.
3. **Handler** comes in and puts its magnet on the part (only now, so the bridges can't meet).
4. **Cutter** cuts the profile through: top flange, web, bottom flange +Y, bottom flange -Y.
5. **Handler** lifts the free part 250 mm, carries it sideways to the outfeed rack and puts it
   down, **while the Cutter is already working on the next part**. Both hands work at once.
6. The last piece: if it has features, the Cutter goes home and the Handler takes it.
   If it has none, it's the remnant and stays on the bed.

Parts heavier than the Handler's 250 kg (for example long HEB300 parts) are left on the bed
for the crane, with a warning.

Every move is safe by construction:
- **Long moves:** column up to 3.0 m, travel, come down.
- **Torch approach:** the torch comes in and out along its own axis, from a point clear of the
  steel (outside the flange for side and tilted cuts).
- **Bridges:** a move that would bring the bridges within 1 m waits for the other hand, or makes
  it back off first.

Afterwards `gantry/check.py` replays the whole plan every 0.3 s. It checks every arm link and
tool against the steel (top flange, web and bottom flange as separate solid boxes, with
notches and moved parts included) and against the bed.

## 4. Using the app

- **Tool** (Hole / Slot / Notch / Cut / Delete) + **Size** + **Slot len / depth**, then click on
  the **TOP FLANGE** or **WEB** strip. Mouse wheel zooms a strip, right-click zooms out.
  - Size = hole diameter, slot width, or notch length (mm).
  - Slot len / depth = slot length, or notch depth (mm).
  - A feature that breaks a rule, or would spoil an existing one, is refused with the reason.
- **PLAN** plans both hands and runs the collision check (a few seconds).
- **RUN / PAUSE**, the **Time** slider to jump, **Speed** 1-60x.
- **View**: whole cell, follow the Cutter, follow the Handler, or from above.
- **Save / Load** writes `my_job.json`. **Demo** loads the example job for the current profile.
- The status line shows what each hand is doing, plus all 9 axes of both hands.

Arduino (optional): the servo shows where the Cutter's bridge is along the 12 m, and the
knob sets the playback speed.

## 5. Code map

| File | What's in it |
|---|---|
| `gantry/arm.py` | 6-axis arm (scalable UR5 geometry), IK for any tool direction (damped least squares, exact Jacobian) |
| `gantry/machine.py` | cell layout, axis limits and speeds, `Hand` (bridge + carriage + column + arm), elbow-up pose search |
| `gantry/beam.py` | profiles, `Job` (features, parts, rules, JSON), part solids with notches, torch paths, demo job |
| `gantry/planner.py` | turns a job into timed tracks for both hands, keeping the bridges apart |
| `gantry/check.py` | arm/tool vs steel collision check over a whole plan |
| `gantry/shapes.py` | solid boxes and tubes with simple lighting for the 3D view |
| `gantry/randomjob.py` | random valid jobs for testing |
| `gantry_cell.py` | the app: 3D view, beam layout editor, playback |
| `test_gantry.py` | headless tests (CI runs them on every push) |

## 6. Next steps (ideas, roughly in order)

1. **DSTV / NC1 import**: the standard file format steel-detailing software (Tekla, Advance
   Steel) exports for beam CNC machines. Read real drawings instead of clicking features.
2. **More shapes**: channels (UPN/PFC), angles, box sections; mitre and bevel cuts (tilted
   torch for weld preps).
3. **Two-hand lift** for heavy parts: the Cutter swaps its torch for a second magnet at a tool
   changer, and both hands lift together (needs synchronised motion).
4. **Scrap handling**: notch slugs and the remnant into a scrap bin.
5. **Beam measuring**: real beams are bent and twisted, so touch-sense or laser-scan the beam
   first and correct the paths.
6. **Hardware scale model**: two servos for the bridges on a short rail (the Arduino already
   drives one), then a real controller (LinuxCNC or ROS 2 + MoveIt).
