# NC1 (DSTV) files

NC1 is the plain-text format that steel detailing software writes for beam CNC machines:
one file per part. **Tekla Structures**, **Advance Steel** and **SDS2** all export it. The cell
reads it in `beamcell/nc1.py`.

## Getting NC1 files out of Tekla

In Tekla Structures: **Manufacturing → NC files → DSTV** (older versions: *File → Export →
NC files*). Pick the parts, choose the output folder, and Tekla writes one `.nc1` file per
part. Then drag the files onto the **Parts** tab. The exact menu names change between
Tekla versions - search the Tekla help for "NC files".

## What is read

| Block | What it is | What the cell does |
|---|---|---|
| `ST` | header: order, drawing, phase, **mark**, **grade**, **quantity**, **profile**, profile type, **length**, h, b, tf, tw, r, kg/m, paint area, **end-cut angles**, texts | used |
| `BO` | holes; with a slot length they're slotted holes | cut |
| `AK` | outer contour of a face: end cuts, mitres, notches/copes | cut |
| `IK` | inner contour: an opening inside a face | cut |
| `SI` | hard stamping (marks) | listed in the report, not cut |
| `KO`, `PU` | marking lines / powder marking | listed, not cut |
| `KA`, `SC`, `TO`, `UE` ... | bending, saw cuts, tolerances, camber | listed, not used |
| `EN` | end of the file | - |

Comment lines start with `**`.

### Header (ST) - one value per line, in this order
1 order, 2 drawing, 3 phase, 4 piece mark, 5 steel grade, 6 quantity, 7 profile name,
8 profile type (`I`, `U`, `L`, `M`, `RO`, `RU`, `B`, `C`, `T`), 9 length (and saw length after
a comma), 10 depth, 11 width, 12 flange thickness, 13 web thickness, 14 root radius,
15 kg/m, 16 paint m²/m, 17 web start cut, 18 web end cut, 19 flange start cut,
20 flange end cut, 21-24 texts.

### Profile names
Names like `UB457*191*67`, `UKB457x191x67`, `457x191x67UB`, `PFC200*90*30`, `L100*100*10`
are matched to the UK library. If a name isn't found (e.g. a European `HE300A`), the sizes in
the header are used and the report says so.

### Faces and coordinates (mm)
| Letter | Face | y is measured |
|---|---|---|
| `v` | front: the web, or the upright leg of an angle | up from the underside of the section |
| `o` | top flange | across from the front edge |
| `u` | bottom flange, or the flat leg of an angle | across from the front edge (the heel for angles) |
| `h` | behind: the back of the web | as `v` (holes go through the web) |

x is always along the part from its start.

**Please check this with your own files**: the DSTV standard defines exactly where y starts
on each face of each profile type, and some exporters have options. Import one of your parts,
look at the drawing on the Parts tab, and compare it with the Tekla drawing. If the holes
come out mirrored across a flange, tell the software maintainer which file and which face.

## Writing NC1

**Export NC1** on the Parts tab writes any part (including ones you made by hand) back out as
an NC1 file, with its holes and every face's outline, so it can go to a real beam line.

## Examples

`examples/nc1/` has seven files: notched secondary beams (B1), a trimmer (B2), a primary
beam with a service opening (G1), a column (C1), a channel (P1), bracing angles (A1) and one
laid out exactly like a Tekla export (T1).
