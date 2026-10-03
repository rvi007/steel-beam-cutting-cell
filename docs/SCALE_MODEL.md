# Building a scale model of the cell

You can build the cell yourself at any scale. All the sizes below come from the software
(`beamcell/machine.py`), so the model matches what you see on screen.

## 1. Get the 3D files

Open the app, go to **Section library**:

- **Download section STL**: any UK section (UB, UC, PFC, angles, hollow sections) at any
  length and scale. The STL is in millimetres, already scaled, ready for a slicer.
- **Download whole machine STL**: the whole cell (runways, columns, bridges, both arms in
  their current pose, bed, rack, fence posts) at the chosen scale. Pause the machine where
  you like the pose first.

The panel tells you the printed size and warns when a wall becomes too thin to print
(under about 0.8 mm with a 0.4 mm nozzle).

## 2. Choosing a scale

| Scale | 12 m work area | Cell (with parking) | Rail height | UB 457 beam | Good for |
|---|---|---|---|---|---|
| 1:10 | 1200 mm | 1460 x 300 mm | 340 mm | 45 x 19 mm | a working prototype with motors |
| 1:20 | 600 mm | 730 x 150 mm | 170 mm | 23 x 9.5 mm | a desk model, fully 3D printed |
| 1:25 | 480 mm | 585 x 120 mm | 136 mm | 18 x 7.6 mm | a desk model |
| 1:50 | 240 mm | 290 x 60 mm | 68 mm | 9 x 3.8 mm | display only (thin parts are fragile) |
| 1:100 | 120 mm | 146 x 30 mm | 34 mm | 4.5 x 1.9 mm | display only, resin printer |

At 1:50 and 1:100 the flanges and webs are thinner than a normal 3D printer can make
(a 10 mm web becomes 0.2 mm at 1:50). Print them with a resin printer, or thicken them
(print the section at 1:20 and use it as a "chunky" stand-in).

## 3. The machine's sizes (full size, metres)

| Item | Size |
|---|---|
| Work area (stock bar) | 12.0 m long, X from 0 to 12 |
| Rails | X from -1.3 to 13.3 (room to park both bridges), 3.0 m apart, top at 3.4 m |
| Runway beams | UB 457x191 on their side, on UC 254x254 columns (5 per side) |
| Bed (rollers) | top at 0.9 m, along Y = -0.5 m (the bar's centre line) |
| Outfeed rack | top at 0.9 m, along Y = +0.85 m |
| Bridges | box girder 0.32 x 3.5 m, 0.42 m deep, one for each hand |
| Column (Z axis) | arm base from 1.25 m to 3.0 m above the floor |
| Bridges never closer than | 1.0 m centre to centre |

**Cutter arm** (UR5-like, hangs upside down): upper arm 425 mm, forearm 392 mm, wrist
offsets 109 / 95 / 82 mm, torch 400 mm long.

**Handler arm** (1.3x bigger): upper arm 552 mm, forearm 510 mm, wrist offsets 142 / 123 /
107 mm, magnet 120 mm, payload 500 kg.

## 4. A working 1:10 prototype (suggested parts)

This is a sensible way to make the model move, controlled from the Jetson. It's a
suggestion, not part of the software yet.

| Job | Suggestion |
|---|---|
| Frame / runways | 20 x 20 mm aluminium extrusion, 1.5 m long, on 4 legs 300 mm high |
| X (each bridge) | linear rail (MGN9 or MGN12) along each runway, GT2 belt, NEMA 17 stepper |
| Y (each carriage) | MGN9 rail on the bridge, GT2 belt, small stepper |
| Z (column) | lead screw (T8) and a NEMA 14/17 stepper |
| Arms | at 1:10 the arms are only ~85 mm long: use a 3-4 servo mini arm, or a fixed tool (torch / magnet) on the Z column for the first version |
| Motor drivers | a USB motion board (e.g. a 3D printer board running GRBL or Klipper) - the Jetson sends it moves over USB; the Jetson's own pins can't make step pulses fast enough |
| Limit switches | one per axis, for homing |
| Camera | any USB webcam on a post looking at the "gate", as in the 3D view |
| "Steel" | 3D printed sections from the library at 1:10 |

The planner already produces the gantry X, Y, Z for every moment of the job
(`plan.tracks` in the plan, in metres) - dividing by 10 gives the model's positions.

## 5. Tips

- Print sections lying on a flange (I sections) or flat leg (angles) so no supports are needed.
- Paint the runways grey, the bridges safety yellow (RAL 1003), the Cutter orange and the
  Handler blue so it matches the screen.
- Mark the work area 0 to 12 m on the base every metre - it makes the demo easy to follow.
