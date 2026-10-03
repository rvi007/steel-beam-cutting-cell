# The machine and how a job runs

## Layout

```
   Y (width 3 m)            safety fence all round, gate + light curtain at the front
   ^      runway beams (UB on UC columns), rails at 3.4 m
   |  ==================================================================
   |   outfeed rack (green)     y = +0.85   finished parts
   |
   |   stock bar on rollers     y = -0.50   up to 12 m, scrap skip below the start
   |  ==================================================================
   +----------------------------------------------------------------------> X (12 m)
        HANDLER bridge (blue) ->                     <- CUTTER bridge (orange)
        parks at x = -1.1                                parks at x = 13.1
```

| | Cutter (orange) | Handler (blue) |
|---|---|---|
| Job | plasma torch: holes, slots, openings, notches, end cuts, cut-off | magnet: holds each part while it's cut free, puts it on the rack |
| Gantry axes | X bridge 1.0 m/s, Y carriage 0.8 m/s, Z column 0.5 m/s | same |
| Arm | 6 axes, UR5 geometry (upper arm 425 mm), hung upside down | 6 axes, 1.3x bigger |
| Tool | 400 mm plasma torch (long, to reach under wide flanges) | magnet pad, 500 kg |
| Total | 9 axes | 9 axes |

Both bridges share the rails: the Handler works on the low-X side, the Cutter on the high-X
side, and the planner keeps them at least **1 m** apart at every moment. Both arms work
**elbow up** (like real ceiling-mounted robots): the whole arm stays above the tool tip.

## How sections lie on the bed

| Section | Lies | Torch passes for a cut |
|---|---|---|
| UB / UC / UBP | web upright, centred | top flange straight down; web from the +Y side (between the flanges); bottom flange with the torch tilted 45° from each side of the web |
| PFC | web upright on the +Y side, flanges pointing -Y | top flange down; web from outside; bottom flange tilted 45° from the open side |
| Angles | longer leg upright on the +Y side, other leg flat | upright leg from the side; heel corner tilted 45°; flat leg straight down |
| Hollow | not cut (needs a chuck) | - |

Holes are cut straight through their plate: top flange from above, web from the side, the
flat leg of an angle from above. Bottom-flange holes on I sections and channels can't be
reached.

## How a bar is cut

1. Parts are **nested** on the bar: 10 mm trimmed off the rough mill end, then part after
   part. Two square ends share one cut; a notched or mitred end gets a 20 mm gap.
2. For each part, from X = 0 upwards:
   1. holes, slots and openings (top flange work first, then the web);
   2. the start cut, unless it shares the previous part's cut-off - the offcut drops into the skip;
   3. the Cutter goes to the cut-off and waits; the **Handler** comes in and puts its magnet on the part;
   4. the cut-off, face by face;
   5. the Handler lifts the part 250 mm, carries it to the outfeed rack and puts it down,
      while the Cutter starts on the next part.
3. A last part that reaches the end of the bar needs no cut-off: the Cutter moves out of the
   way and the Handler takes it. Anything left over is the remnant and stays on the bed.

Long cuts (over 150 mm - webs of deep beams, flanges) move the gantry with the torch, as a
real machine's coordinated axes do; short ones (holes) use the arm alone.

## Safety, by construction and by checking

- **Bridges**: a move that would bring them within 1 m waits for the other hand, or makes it back off.
- **Travel**: long moves lift the column to 3.0 m, travel, then come down.
- **Torch approach**: the torch comes in and leaves along its own axis, from a point outside the section.
- **Collision check** (`beamcell/collisions.py`): the whole plan is replayed every 0.4 s and every
  arm link and tool is checked against the steel (each plate following its real outline, so
  notches count; offcuts until they drop; carried parts where they are) and the bed.
- **Safety controller** (`beamcell/safety.py`): E-stop, gate, light curtain, extraction, camera
  zones, modes, watchdogs - every stop latches; Reset then Start (see `SAFETY.md`).

`tests/sweep_sections.py` plans a typical part on **every one of the 267 cuttable UK
sections** (from a 20x20 angle to UB 1016x305x584) and checks all of the above: 0 problems.

## Timing

Plasma speeds follow typical 130 A values: 50 mm/s up to 6 mm thick down to 10 mm/s over
20 mm; tilted cuts count as 1.4x the thickness. Each pierce takes 0.6 s. A typical bar of two
5.2 m notched secondary beams takes about 7.5 minutes.

## Code map

| File | What it does |
|---|---|
| `beamcell/sections.py` | UK section library, exact outlines with radii, plates and DSTV faces |
| `beamcell/uk_codes.py` | BS EN 1090-2 / BS EN 1993-1-8 / SCI values |
| `beamcell/parts.py` | parts, face outlines (notches, mitres), cut chains, UK checks, nesting onto bars |
| `beamcell/nc1.py` | reads and writes DSTV NC1 files |
| `beamcell/arm.py` | 6-axis arm kinematics, IK for any tool direction |
| `beamcell/machine.py` | the cell's sizes, the two hands, comfortable elbow-up poses |
| `beamcell/planner.py` | turns a bar into timed tracks for both hands |
| `beamcell/collisions.py` | replays a plan and checks arms against the steel |
| `beamcell/vision.py` | camera, YOLO / HOG person detection, warning + danger zones |
| `beamcell/safety.py` | safety controller: E-stop, interlocks, modes, reset/start, watchdogs, ISO 13855 distance |
| `beamcell/gpio_inputs.py` | optional wired E-stop / gate / curtain / reset on the Jetson's pins (fail-safe) |
| `beamcell/assistant.py` | plain-English situation + optional Claude advisor |
| `beamcell/doctor.py` | system check and setup plan |
| `beamcell/config.py` | reads `config/cell.toml` |
| `beamcell/server.py` | web server and JSON API |
| `web/js/scene.js` | the 3D cell (three.js) |
| `web/js/geometry.js` | steel parts plate by plate, with real holes and notches |
| `web/js/app.js` | playback of the plan, the Machine tab |
| `web/js/parts.js` | Parts tab: NC1 import, editor, drawing, checks |
| `web/js/library.js` | Section library and STL export |
| `web/js/camera.js` | Camera tab |

## Next steps (ideas)

1. Read real NC1 files from your Tekla models and compare the drawings (see `NC1_FILES.md`).
2. Train a YOLO model to see the **beam** (its end and position) so the Cutter corrects for
   where the bar really lies.
3. Bevel cuts for weld preparation (the torch is already 6-axis).
4. Drive a 1:10 model's motors from the plan (see `SCALE_MODEL.md`).
5. Two-hand lifting for parts over 500 kg.
