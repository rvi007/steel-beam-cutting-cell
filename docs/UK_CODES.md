# UK codes used by the cell

Everything is in millimetres and follows UK practice. The checks run every time you edit a
part, and every message names its source. Code rules live in `beamcell/uk_codes.py`; the
checks are in `Part.check()` in `beamcell/parts.py`.

## Sections

| Family | Standard | In the library |
|---|---|---|
| UB universal beams | BS 4-1:2005 | 107 |
| UC universal columns | BS 4-1:2005 | 46 |
| UBP universal bearing piles | BS 4-1:2005 | 17 |
| PFC parallel flange channels | BS 4-1:2005 | 16 |
| Equal angles | BS EN 10056-1 | 42 |
| Unequal angles | BS EN 10056-1 | 39 |
| SHS / RHS / CHS hot finished | BS EN 10210-2 | 387 |
| SHS / RHS / CHS cold formed | BS EN 10219-2 | 339 |

The sizes (h, b, tw, tf, r, r1, r2, mass, and the detailing values C, N, n) are the ones
published in the SCI/BCSA "Blue Book" (Steel for Life). They were taken from the open-source
`steelsnakes` package (GPL-2.0). Every outline is checked by a test: its area x 7850 kg/m³
matches the published mass. **Check sizes against the current Blue Book or mill data before
real fabrication.**

Hollow section corner radii: hot finished 1.5t outside / 1.0t inside (BS EN 10210-2);
cold formed 2t, 2.5t or 3t outside depending on t (BS EN 10219-2).

Additional sizes (made by the mills but not in BS 4-1) are marked with `*` in the library.

## Rules checked on every part

| Rule | Value | Source |
|---|---|---|
| Normal round hole for a bolt | M12, M14: d + 1; M16 to M24: d + 2; M27 and up: d + 3 | BS EN 1090-2 |
| Oversize hole | M12: +3, M16-M22: +4, M24: +6, M27+: +8 | BS EN 1090-2 |
| Short slot | normal hole + 4 / 6 / 8 / 10 mm longer | BS EN 1090-2 |
| Long slot | 1.5 x bolt diameter longer | BS EN 1090-2 |
| Holes may be thermally (plasma) cut | if the cut quality and hardness rules are met | BS EN 1090-2 |
| End distance e1, edge distance e2 | at least 1.2 d0 | BS EN 1993-1-8 Table 3.3 + UK NA |
| Spacing between holes | at least 2.2 d0 | BS EN 1993-1-8 Table 3.3 + UK NA |
| Holes clear of the web/flange root radius | hole edge outside tf + r | section geometry |
| Re-entrant corners (notches) rounded | at least 5 mm (10 mm used by default) | BS EN 1090-2 |
| Notch depth | at least tf + r so it clears the flange | UK detailing (Blue Book n) |
| Deep or long notches | depth over h/2 or length over h: warning for the engineer | SCI P358 |
| Default bolt | M20 grade 8.8 in 22 mm holes | SCI P358 / UK practice |
| Notch to clear a supporting beam | length N, depth n from that beam's Blue Book entry | Blue Book |
| Steel grades | S275JR/J0/J2, S355JR/J0/J2/K2 | BS EN 10025-2 |

d0 = hole diameter. These are minimums for fabrication checks; the connection design itself
(bolt numbers, plate sizes, notched-beam stability) is the engineer's job.

## Limits of this machine (not code rules)

| Limit | Value | Why |
|---|---|---|
| Smallest plasma hole | the plate thickness, and at least 10 mm | plasma can't make good holes smaller than the plate is thick |
| Shortest part | 150 mm | the Handler's magnet needs something to hold |
| Bottom-flange holes on I sections and channels | not possible | the torch can't reach under the top flange from above - use a drill line or turn the part |
| Hollow sections | not cut | they need a rotating chuck; they're in the library for drawings and 3D printing |
| Heaviest part the Handler lifts | 500 kg | heavier parts stay on the bed for the overhead crane |
| Stock lengths | 6, 8, 10, 12 m | the work area is 12 m |
| Gap between parts | 0 (shared cut) for two square ends, otherwise 20 mm | nesting |
| Mill-end trim | 10 mm | stock ends aren't square |
