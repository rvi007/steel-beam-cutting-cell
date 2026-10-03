# Beam Cell - context for Claude Code

A prototype 12 m structural-steel beam cutting cell (UK codes) with two overhead robot hands:
Cutter (plasma) and Handler (magnet). Python engine (`beamcell/`, stdlib + numpy only) serving
a three.js web app (`web/`). The user runs it on a Jetson Orin Nano (4 GB, see
`docs/JETSON_SPECS.md`) and demos it in a browser. README.md has the folder map.

## Rules for changes
- No new Python dependencies (Jetson is offline-ish, 4 GB RAM). numpy only; OpenCV optional (camera).
- Browser libraries go in `web/vendor/` (no CDN). three.js r160 is vendored.
- UK codes only (BS 4-1, BS EN 10056-1, BS EN 1090-2, BS EN 1993-1-8 + UK NA, SCI P358). Cite the
  source in every check message (`ref`).
- Units: mm for parts/sections/NC1, metres for the machine and the 3D scene. Machine axes: X along
  the 12 m bar, Y across (+Y = Cutter side), Z up.
- Keep plain-English UI text; the user is learning.

## How to check your work
- `python3 -m unittest discover -s tests -t .` (about 40 s) - must pass.
- `python3 tests/sweep_sections.py` - every cuttable section; must report 0 problems.
- Browser: `./start.sh --port 8099 &` then `node tests/ui_smoke.mjs http://localhost:8099`
  (needs playwright; CI runs it).
- Headless screenshots: Playwright + Chromium with `--use-gl=angle --use-angle=swiftshader`.
- Orin-like env for testing: Python 3.12, numpy 1.26.4, opencv-python-headless 4.6.0.66.

## Safety (most important)
- `beamcell/safety.py` is the only thing that decides motion; the browser asks it 5x/s
  (`/api/safety/tick`) and moves only when `may_move`, at `speed_factor`. Keep: latching stops,
  reset never restarts, start separate, checklist, watchdogs, Manual 250 mm/s hold-to-run.
- Never weaken a stop to make a demo easier. Tests in `tests/test_safety.py` and the browser test
  cover the procedures. Say plainly in docs/UI that software stops are not safety-rated.
- The AI advisor (`assistant.py`, Claude via the `anthropic` SDK, off by default) is advisory only and
  must never get a path to move/reset/start anything.
- Settings live in `config/cell.toml` (tomllib); `python3 -m beamcell.doctor` checks a machine.

## Key design points
- Parts are described like NC1: per-face outlines (DSTV faces v/o/u/h) + holes + inner contours.
  Manual copes/mitres are converted to outlines (`Part.face_outline`). Cut paths = outline edges
  that aren't the plate's long edges (`Part.chains`).
- `planner.Placed.classify` maps a face point to a torch pass: D down, S side (+Y), P/N tilted
  45 deg. Arms hang upside down (`machine.FLIP`), elbow-up poses from `Hand.preference`.
- Cuts over 150 mm move the gantry with the torch (coordinated motion); torch is 400 mm long so
  wide UC flanges clear.
- `Plan._commit` keeps the bridges >= 1 m apart against everything the other hand has planned.
- The browser rebuilds a part's plates when its cut state changes (`geometry.partGroup`).

## Status
Working in simulation, tested headless. Not yet run on the user's Orin screen. Next ideas are in
docs/MACHINE.md (YOLO for the beam position, bevels, driving a 1:10 model).
