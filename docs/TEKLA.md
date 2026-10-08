# The steel frame in Tekla Structures

This is for the steel detailer. The cell's fabricated structural steelwork is exported as an IFC model
you can bring into Tekla, convert to native parts, connect up, and get drawings and NC1 files from.

| File | What |
|---|---|
| `cad/beam_cell_steel_12m.ifc` | the 12 m machine's frame (IFC2X3, millimetres) |
| `cad/beam_cell_steel_20m.ifc` | the 20 m machine's frame |
| `cad/beam_cell_steel_12m.csv`, `_20m.csv` | cut lists: every mark, then totals by profile, then the grand total |

Made by `python3 -m beamcell.ifc_export` (code in `beamcell/ifc_export.py`, checks in `tests/test_ifc.py`).
Run it again after any change to the machine's sizes in `beamcell/machine.py`.

## Importing into Tekla

The file is **IFC2X3** (Coordination View 2.0 style), which Tekla imports most reliably. There are two ways in.

**1. As a reference model, then convert (recommended).**
1. *Manage > Reference model* (older versions: *File > Insert reference model*), pick the .ifc, insert at 0,0,0, scale 1.
2. Select the reference objects, right-click *Convert IFC objects* (or *Manage > Convert IFC objects*).
3. Tekla makes real beams, columns and plates with the profile, material and position from the file. Check
   the conversion log for anything left as a "brep" - there should be nothing; every member is a simple extrusion.

**2. File > Import > IFC** (older versions and some environments). It makes Tekla parts straight away.
Use this if you don't want a reference model hanging about.

**Profile and material mapping.** Each member's profile name is already in the Tekla UK catalogue format:
`UB457*191*67`, `UC254*254*73`, `RHS120*80*5`, `RHS100*80*5`, `SHS80*80*5`, `SHS100*100*6.3`, `L70*70*7`,
`PL25*500`, `PL20*300`, `FL60*50`, `FL60*30`. It's in three places: the profile (`ProfileName`), the element's
`ObjectType`/`Description`, and the property set. If your environment names something differently (e.g. `EA70*70*7`
rather than `L70*70*7`), add a line to the conversion's profile mapping file (`ProfileConversion.cnv` /
*IFC object conversion > Profile mapping*) rather than editing the model. The material is `S355` throughout: map
it to S355J2 (or S355J2H for the hollow sections) in the material mapping if your catalogue wants the sub-grade.

After converting, run *Clash check* against your connections and *Numbering* - Tekla will renumber; the marks
below are only for referring back to this model and the cut list.

## Coordinates

- Origin: the **bar datum** - the face of the bar end stop on the bed's centre line, at finished floor level.
- **X** along the bed, infeed end towards outfeed end. **Y** across: the front runway is at Y = -1500, the back at Y = +1500.
  **Z** up from finished floor level (top of slab = 0).
- Millimetres. Every position and length is rounded to 1 mm.

## What's in the model

Each member is an `IfcBeam`, `IfcColumn`, `IfcPlate` or `IfcMember` with `Name` = mark, and a property set
`Pset_BeamCellSteel` with **Mark, Assembly, Profile, Grade, Length, Weight** and, where useful, **Notes**
(holes, splices, fixings). Members are grouped by `IfcElementAssembly` per assembly below.

| Assembly | Marks | Members |
|---|---|---|
| RUNWAY-FRONT / RUNWAY-BACK | RB, R | Runway beams UB 457x191x67, underside at Z 2850, running 300 mm past the end columns. Crane rail 60x50 flat (FL60*50) on top, top at Z 3353.4. |
| COLUMNS-FRONT / COLUMNS-BACK | C, BP, CP | Columns UC 254x254x73 (web along X) at no more than 4 m centres, Z 25 to 2830. Base plates PL25 500x500 under each, cap plates PL20 300x300 on top. |
| BRACING-FRONT / BRACING-BACK | BX | X-bracing, two L70x70x7 diagonals in the first bay at the infeed end, in the plane of the columns, passing either side of a centre gusset. |
| TRAY-FRONT / TRAY-BACK | TB | Energy-chain tray brackets, 60x30 flat, under the runway, sticking out 350 mm outboard. |
| BED | BR, BL | Roller bed side rails RHS 120x80x5 (Y -900 and -100, top at Z 810), legs SHS 80x80x5 every 2 m. |
| OUTFEED | OF, OL | Outfeed table rails RHS 100x80x5 (100 high, top at Z 870), legs SHS 80x80x5 every 2 m. |
| END-STOP | ES, ESP | Bar end stop post SHS 100x100x6.3 on a PL20 300x300 base plate, top at Z 880. |

**Things I've added so a fabricator can make it** (they are not in the 3D view of the machine):
- Cap plates PL20 300x300 on every column; the runway's bottom flange bolts to them. Columns are shortened by 20 mm to suit.
- Base plates carry a note: 4 holes 26 dia for M24 holding-down bolts at 380 centres, 25-40 mm grout. The holes are data only - not cut in the model.
- **Runway splice (20 m machine only).** The runway is 23.2 m long, too long for stock, so it's in two 11.6 m lengths spliced over the column at X 10000. The crane rail is split at the same place - stagger the rail joint from the beam joint if you can (500 mm or more). The 12 m machine's runway is one 15.2 m length.
- Bed and outfeed rails are in two equal lengths (hollow stock is 12 m), joined over a leg.
- Longitudinal X-bracing in one bay a side.

## What is NOT designed - needs a structural engineer

- **Connections**: splices, cap plate bolts, bracing gussets, bed and leg feet - all yours to design and detail (to BS EN 1993-1-8 / the engineer's forces).
- **End-frame (cross-wise) stability.** There is no cross-tie between the two runway lines, on purpose: the bridges run on top of the runways and the masts and arms hang down to bed level, so any steel between the runways would be in their way. The machine's moving envelope is X from the rail end -0.5 m to the other end +0.5 m, Y -1250 to +1250, Z 900 to 4100 - **no steel may go in that box**. Cross-wise stability must come from moment-fixed column bases, or from ties above Z 4100, or from steel outside the fence. The structural engineer decides.
- **Crane loads**: the bridges' wheel loads, surge and braking forces, and the runway's deflection limits (span/600 or tighter for rail alignment) - the engineer checks the UB 457x191x67 and the columns.
- **Foundations** and holding-down bolts (sizes above are only a starting point).
- **Rail fixing**: shown as a flat bar on the top flange. Clips or continuous welding, and rail tolerances, are the engineer's and the crane supplier's call.

Bought-in items (the grating deck, rollers and bearings, the datum block and laser on the end stop, the fence, the energy chains and their trays) are not in the model.

## Cut list totals

Weights are plain section weight x length (plates: area x thickness x 7850 kg/m3). Bolts, welds, gussets and connection plates are **not** included - allow 5-10 % more.

| Profile | 12 m: qty | 12 m: length (m) | 12 m: kg | 20 m: qty | 20 m: length (m) | 20 m: kg |
|---|---|---|---|---|---|---|
| UB457*191*67 | 2 | 30.4 | 2040 | 4 | 46.4 | 3114 |
| UC254*254*73 | 10 | 28.1 | 2050 | 14 | 39.3 | 2870 |
| FL60*50 (crane rail) | 2 | 30.4 | 716 | 4 | 46.4 | 1093 |
| PL25*500 (base plates) | 10 | - | 491 | 14 | - | 687 |
| PL20*300 (cap plates + end stop base) | 11 | - | 155 | 15 | - | 212 |
| L70*70*7 | 4 | 16.5 | 122 | 4 | 16.9 | 125 |
| RHS120*80*5 | 4 | 25.2 | 370 | 4 | 41.2 | 606 |
| RHS100*80*5 | 4 | 25.2 | 322 | 4 | 41.2 | 527 |
| SHS80*80*5 | 28 | 20.4 | 237 | 44 | 32.1 | 372 |
| SHS100*100*6.3 | 1 | 0.9 | 16 | 1 | 0.9 | 16 |
| FL60*30 (tray brackets) | 8 | 4.2 | 60 | 12 | 6.4 | 90 |
| **Total** | **84 members** | | **6,579 kg** | **120 members** | | **9,710 kg** |
