"""
Real CAD for the cell, the parts and the 1:10 prototype - solid models you can open in Fusion 360,
SolidWorks, FreeCAD, Onshape or Inventor (STEP), and the same model for the 3D view (GLB).

    python3 -m beamcell.cad                    everything below
    python3 -m beamcell.cad cell               cad/beam_cell.step  + web/models/*.glb (the 3D view)
    python3 -m beamcell.cad parts [files.nc1]  cad/parts/<mark>.step - one solid per NC1 part, with its
                                               holes, slots, notches and end cuts (default: examples/nc1)
    python3 -m beamcell.cad prototype          cad/prototype_1to10.step + cut list + positions + the Prototype tab's model

Needs CadQuery (pip install cadquery) - run it on a PC. The Jetson doesn't need it: the files
it makes are in the repo.

Units: STEP files in millimetres, GLB files in metres. Axes as everywhere in the project:
X along the bar (infeed -> outfeed end), Y across (+Y = the Cutter's side), Z up.

Every solid has a name and a label. The labels say what each thing is and, for the prototype,
what to buy or make - the 3D view shows them when you point at something.
"""
import csv
import glob
import math
import os
import sys

import numpy as np

from beamcell import machine as M
from beamcell import sections as S

try:
    import cadquery as cq
    from cadquery.occ_impl.exporters.assembly import exportGLTF
except ImportError:                                   # fine on the Jetson: the files are in the repo
    cq = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAD_DIR = os.path.join(ROOT, "cad")
WEB_MODELS = os.path.join(ROOT, "web", "models")
RUNWAY_Z = M.RAIL_Z * 1000 - 550            # underside of the runway beams (UB 457x191x67, 453.4 deep)
CRANE_RAIL_TOP = RUNWAY_Z + 453.4 + 50      # top of the 50 mm crane rail on the runway: the wheels stand on it

# colours (0..1 RGB) - the same as the 3D view
STRUCTURE = (0.42, 0.45, 0.49)
YELLOW = (0.95, 0.76, 0.19)
DARK = (0.17, 0.19, 0.22)
STEEL = (0.44, 0.47, 0.50)
RUBBER = (0.10, 0.10, 0.10)
GREEN = (0.30, 0.55, 0.38)
BLUE_TRAY = (0.18, 0.37, 0.55)
BED = (0.33, 0.22, 0.16)
ALU = (0.75, 0.77, 0.80)
PRINTED = (0.92, 0.45, 0.12)
RED = (0.85, 0.12, 0.09)


def need_cadquery():
    if cq is None:
        raise SystemExit("CAD export needs CadQuery: pip install cadquery  (on a PC - the Jetson doesn't need it,\n"
                         "the STEP and GLB files are already in cad/ and web/models/)")


# ======================================================================= sections with true arcs
def _outline_path(s):
    """The cross-section as straight lines and true arcs: [("L", (u, v)) | ("A", cx, cy, r, a0, a1)]
    (mm, same shape and direction as sections.outline())."""
    k, h, b = s["kind"], s["h"], s["b"]
    if k == "I":
        tw, tf, r = s["tw"], s["tf"], s["r"]
        w = tw / 2
        return [("L", (-b / 2, 0)), ("L", (b / 2, 0)), ("L", (b / 2, tf)),
                ("A", w + r, tf + r, r, -90, -180), ("A", w + r, h - tf - r, r, 180, 90),
                ("L", (b / 2, h - tf)), ("L", (b / 2, h)), ("L", (-b / 2, h)), ("L", (-b / 2, h - tf)),
                ("A", -w - r, h - tf - r, r, 90, 0), ("A", -w - r, tf + r, r, 0, -90), ("L", (-b / 2, tf))]
    if k == "U":
        tw, tf, r = s["tw"], s["tf"], s["r"]
        x = b / 2 - tw
        return [("L", (-b / 2, 0)), ("L", (b / 2, 0)), ("L", (b / 2, h)), ("L", (-b / 2, h)), ("L", (-b / 2, h - tf)),
                ("A", x - r, h - tf - r, r, 90, 0), ("A", x - r, tf + r, r, 0, -90), ("L", (-b / 2, tf))]
    if k == "L":
        t, r1, r2 = s["t"], s["r1"], s["r2"]
        x = b / 2 - t
        return [("L", (-b / 2, 0)), ("L", (b / 2, 0)), ("L", (b / 2, h)),
                ("A", x + r2, h - r2, r2, 90, 180), ("A", x - r1, t + r1, r1, 0, -90),
                ("A", -b / 2 + r2, t - r2, r2, 90, 180)]
    raise ValueError(k)


def _wire(wp, path):
    """Draw a closed path on a workplane: lines and true arcs."""
    def at(cx, cy, r, a):
        return (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))

    first = path[0][1] if path[0][0] == "L" else at(*path[0][1:4], path[0][4])
    wp = wp.moveTo(*first)
    cur = first
    for seg in path[1:] if path[0][0] == "L" else path:
        if seg[0] == "L":
            if math.dist(cur, seg[1]) > 1e-6:
                wp = wp.lineTo(*seg[1])
            cur = seg[1]
        else:
            cx, cy, r, a0, a1 = seg[1:]
            p0, pm, p1 = at(cx, cy, r, a0), at(cx, cy, r, (a0 + a1) / 2), at(cx, cy, r, a1)
            if math.dist(cur, p0) > 1e-6:
                wp = wp.lineTo(*p0)
            wp = wp.threePointArc(pm, p1)
            cur = p1
    return wp.close()


SECTION_PLANE = dict(origin=(0, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))     # section u -> Y, v -> Z


def section_solid(s, length):
    """A plain length of any UK section along +X from 0 (mm)."""
    plane = cq.Plane(**SECTION_PLANE)
    k = s["kind"]
    if k in ("I", "U", "L"):
        return _wire(cq.Workplane(plane), _outline_path(s)).extrude(length)
    if k == "M":
        t = s["t"]
        outer = cq.Workplane(plane).center(0, s["h"] / 2).rect(s["b"], s["h"]).extrude(length).edges("|X").fillet(s["ro"])
        inner = cq.Workplane(plane).center(0, s["h"] / 2).rect(s["b"] - 2 * t, s["h"] - 2 * t).extrude(length)
        if s["ri"] > 0:
            inner = inner.edges("|X").fillet(s["ri"])
        return outer.cut(inner)
    if k == "RO":
        d, t = s["d"], s["t"]
        return cq.Workplane(plane).center(0, d / 2).circle(d / 2).circle(d / 2 - t).extrude(length)
    raise ValueError(k)


# ======================================================================= a part with its holes and cuts
def _band(s, pl):
    """How far a cut-out on this plate goes through the steel: (lo, hi) mm, across the plate
    (Y for upright plates, Z for flat ones) - the plate, plus the root radius next to it."""
    k = s["kind"]
    if k == "L":
        t, r1 = s["t"], s["r1"]
        return (s["b"] / 2 - t - r1, s["b"] / 2 + 1) if not pl["flat"] else (-1, t + r1)
    r = s["r"]
    if pl["flat"]:
        return (pl["v0"] - r, pl["v1"] + 1) if pl["face"] == "o" else (pl["v0"] - 1, pl["v1"] + r)
    return (pl["u0"] - r, pl["u1"] + r) if k == "I" else (pl["u0"] - r, pl["u1"] + 1)


def _face_plane(s, pl, lo):
    """Workplane for drawing in a plate's own face coordinates (x along, y across like NC1)."""
    if pl["flat"]:   # local x = X, local y = Y; extrude +Z from lo
        return cq.Plane(origin=(0, 0, lo), xDir=(1, 0, 0), normal=(0, 0, 1))
    return cq.Plane(origin=(0, lo, 0), xDir=(1, 0, 0), normal=(0, 1, 0))     # local y = -Z: see _to_local


def _to_local(s, pl, x, y):
    """NC1 face point -> 2D point on _face_plane."""
    if pl["flat"]:
        return (x, S.face_to_section(s, pl["face"], y))
    return (x, -y)


def _prism(s, pl, pts, band):
    lo, hi = band
    local = [_to_local(s, pl, x, y) for x, y in pts]
    return cq.Workplane(_face_plane(s, pl, lo)).polyline(local).close().extrude(hi - lo)


def part_solid(part):
    """A part as one solid (mm, along +X from 0): the section with every notch, end cut, hole,
    slot and opening cut out exactly as the NC1 file / part editor says."""
    s = part.sec
    L = part.length
    body = section_solid(s, L)
    by_face = {p["face"]: p for p in S.plates(s)}
    for pl in S.plates(s):
        outline = part.face_outline(pl["face"])
        W = S.face_width(s, pl["face"])
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        if len(outline) == 4 and min(xs) > -0.01 and max(xs) < L + 0.01 and min(ys) > -0.01 and max(ys) < W + 0.01 \
                and abs(max(xs) - min(xs) - L) < 0.01:
            continue                                                    # plain square ends: nothing to cut
        band = _band(s, pl)
        everything = _prism(s, pl, [(-2, -2), (L + 2, -2), (L + 2, W + 2), (-2, W + 2)], band)
        body = body.cut(everything.cut(_prism(s, pl, outline, band)))
    for hole in part.holes:
        pl = by_face.get(part.hole_face(hole))
        if pl is None:
            continue
        lo, hi = (pl["v0"] - 1, pl["v1"] + 1) if pl["flat"] else (pl["u0"] - 1, pl["u1"] + 1)
        cx, cy = _to_local(s, pl, hole["x"], hole["y"])
        wp = cq.Workplane(_face_plane(s, pl, lo)).center(cx, cy)
        slot = hole.get("slot") or 0
        if slot > hole["d"]:
            ang = hole.get("angle", 0) or 0
            wp = wp.slot2D(slot, hole["d"], -ang if pl["flat"] else -ang)
        else:
            wp = wp.circle(hole["d"] / 2)
        body = body.cut(wp.extrude(hi - lo))
    for item in part.inner:
        pl = by_face.get(part.norm_face(item["face"]))
        if pl is not None:
            lo, hi = (pl["v0"] - 1, pl["v1"] + 1) if pl["flat"] else (pl["u0"] - 1, pl["u1"] + 1)
            body = body.cut(_prism(s, pl, item["points"], (lo, hi)))
    return body


def export_parts(paths, out_dir=None):
    """One STEP file per NC1 part. Returns the files written."""
    need_cadquery()
    from beamcell import nc1
    out_dir = out_dir or os.path.join(CAD_DIR, "parts")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for path in paths:
        with open(path) as fh:
            part, _ = nc1.read(fh.read(), os.path.basename(path))
        if part.sec["kind"] not in S.CUTTABLE:
            continue
        out = os.path.join(out_dir, f"{part.mark}.step")
        cq.exporters.export(part_solid(part), out)
        written.append(out)
    return written


# ======================================================================= building blocks
class Model:
    """Named, labelled, coloured solids (mm). Becomes a STEP assembly and a GLB for the 3D view.
    `group` puts a solid in a moving body (e.g. 'cutter.bridge'); static things have group None."""

    def __init__(self, name):
        self.name = name
        self.items = []            # (group, name, label, workplane/shape, colour)
        self.names = {}
        self.cuts = []             # aluminium extrusions to cut: (profile, length mm, what for)

    def add(self, name, label, shape, colour, group=None):
        n = self.names.get(name, 0)
        self.names[name] = n + 1
        self.items.append((group, f"{name}_{n + 1}" if n else name, label, shape, colour))
        return shape

    def box(self, name, label, colour, x0, x1, y0, y1, z0, z1, group=None):
        shape = cq.Workplane().box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))
        return self.add(name, label, shape, colour, group)

    def cyl(self, name, label, colour, p0, p1, r, group=None, r1=None):
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = p1 - p0
        L = float(np.linalg.norm(d))
        if L < 1e-6:
            return None
        if r1 is None:
            solid = cq.Solid.makeCylinder(r, L, cq.Vector(*p0), cq.Vector(*(d / L)))
        else:
            solid = cq.Solid.makeCone(r, r1, L, cq.Vector(*p0), cq.Vector(*(d / L)))
        return self.add(name, label, cq.Workplane().add(solid), colour, group)

    def hollow(self, name, label, colour, w, h, t, p0, p1, group=None):
        """A real RHS / SHS (w x h x t, outer corner radius 2t, inner t) between two points on one axis.
        w is across in the first other axis (Y for X members, X for Z members), h in the second."""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        axis = int(np.argmax(np.abs(p1 - p0)))
        L = float(abs(p1[axis] - p0[axis]))
        outer = cq.Workplane("XY").rect(w, h).extrude(L).edges("|Z").fillet(min(2 * t, w / 2 - 0.1, h / 2 - 0.1))
        inner = cq.Workplane("XY").rect(w - 2 * t, h - 2 * t).extrude(L).edges("|Z").fillet(max(t, 0.5))
        shape = outer.cut(inner)
        if axis == 0:
            shape = shape.rotate((0, 0, 0), (0, 1, 0), 90).rotate((0, 0, 0), (1, 0, 0), 90)   # Z -> X; w along Y, h along Z
        elif axis == 1:
            shape = shape.rotate((0, 0, 0), (1, 0, 0), -90)
        start = np.minimum(p0, p1)
        shape = shape.translate(tuple(start if axis == 2 else start))
        return self.add(name, label, shape, colour, group)

    def tube(self, name, label, colour, p0, p1, r, t, group=None):
        """A round tube (CHS / roller tube) of outside radius r and wall t."""
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = p1 - p0
        L = float(np.linalg.norm(d))
        u = cq.Vector(*(d / L))
        solid = cq.Solid.makeCylinder(r, L, cq.Vector(*p0), u).cut(cq.Solid.makeCylinder(r - t, L, cq.Vector(*p0), u))
        return self.add(name, label, cq.Workplane().add(solid), colour, group)

    def section(self, name, label, colour, title, length, at=(0, 0, 0), axis="x", group=None):
        """A length of a UK section: along X (lying like on the bed) or standing up (axis='z')."""
        solid = section_solid(S.get(title), length)
        if axis == "z":                                     # X -> Z, the section's v (up) -> -X
            solid = solid.rotate((0, 0, 0), (0, 1, 0), -90)
        return self.add(name, label, solid.translate(tuple(at)), colour, group)

    def extrusion(self, name, label, colour, size, p0, p1, group=None, use=None):
        """Aluminium T-slot extrusion (e.g. 20x40) between two points, drawn as its outer box
        with the four slots grooved along it."""
        a, b = size
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        d = p1 - p0
        L = float(np.linalg.norm(d))
        axis = int(np.argmax(np.abs(d)))
        dims = [0.0, 0.0, 0.0]
        dims[axis] = L
        others = [i for i in range(3) if i != axis]
        dims[others[0]], dims[others[1]] = a, b
        self.cuts.append((f"{min(a, b):.0f}x{max(a, b):.0f}", round(L), use or name.replace("_", " ")))
        lo = np.minimum(p0, p1).copy()
        lo[others[0]] -= a / 2
        lo[others[1]] -= b / 2
        shape = cq.Workplane().box(*dims, centered=False).translate(tuple(lo))
        # slots: 6 mm wide, 6 mm deep, centred on each 20 mm module of each face
        for k, (w_dim, other) in enumerate(((a, others[1]), (b, others[0]))):
            n = int(round(w_dim / 20))
            for i in range(n):
                for side in (0, 1):
                    sd = [0.0, 0.0, 0.0]
                    sd[axis] = L
                    sd[others[k]] = 6.0
                    sd[other] = 6.0
                    pos = lo.copy()
                    pos[others[k]] = lo[others[k]] + 10 + 20 * i - 3
                    pos[other] = lo[other] + (0 if side == 0 else (b if other == others[1] else a) - 6)
                    shape = shape.cut(cq.Workplane().box(*sd, centered=False).translate(tuple(pos)))
        return self.add(name, label, shape, colour, group)

    # ------------------------------------------------------------ output
    def assembly(self, scale=1.0, groups=None):
        """cq.Assembly of the static solids (groups=None) or of the given moving bodies, each moving
        body a sub-assembly named after it ('cutter.link3' -> 'cutter_link3')."""
        assy = cq.Assembly(name=self.name)
        subs = {}
        for group, name, label, shape, colour in self.items:
            if (groups is None) != (group is None) or (groups is not None and group not in groups):
                continue
            obj = shape.val() if hasattr(shape, "val") else shape
            if hasattr(shape, "vals") and len(shape.vals()) > 1:
                obj = cq.Compound.makeCompound([v for v in shape.vals() if isinstance(v, cq.Shape)])
            if scale != 1.0:
                obj = obj.scale(scale)
            if group is None:
                assy.add(obj, name=name, color=cq.Color(*colour))
            else:
                subs.setdefault(group, cq.Assembly(name=group.replace(".", "_"))).add(obj, name=name, color=cq.Color(*colour))
        for group, sub in subs.items():                  # added complete: cq copies a sub-assembly when it's added
            assy.add(sub, name=group.replace(".", "_"))
        return assy

    def labels(self):
        return {name: label for _, name, label, _, _ in self.items}


# ======================================================================= the full-size cell
def _hand_rest(hand):
    side = [1, 0, 0] if hand.tool == "torch" else [-1, 0, 0]
    return hand.preference([0, 0, -1], side)[1]


def build_cell():
    """The 12 m cell at full size - static frame plus each hand's moving bodies, which are built
    in their own frames (the 3D view moves them with the kinematics)."""
    need_cadquery()
    mm = 1000.0
    m = Model("beam_cell")
    xa, xb = M.X_LIMITS
    W = M.WIDTH * mm
    L = (xb - xa + 0.6) * mm
    x0 = (xa - 0.3) * mm
    run_z = RUNWAY_Z                                        # underside of the runway beams
    by, bz = M.BEAM_Y * mm, M.BED_Z * mm

    # building steelwork: runway beams on columns, crane rails
    for side, y in (("front", -W / 2), ("back", W / 2)):
        m.section(f"runway_{side}", "Runway beam UB 457x191x67 - carries a bridge rail", STRUCTURE,
                  "UB 457x191x67", L, at=(x0, y, run_z))
        m.box(f"crane_rail_{side}", "Crane rail 60x50 flat bar - both bridges' wheels run on it", STEEL,
              x0, x0 + L, y - 30, y + 30, CRANE_RAIL_TOP - 50, CRANE_RAIL_TOP)
        bays = math.ceil((xb - xa) / 4.0)                   # a column at least every 4 m: 5 a side at 12 m, 7 at 20 m
        for i in range(bays + 1):
            x = (xa + i * (xb - xa) / bays) * mm
            # standing up, the section's depth runs along -X from 'at': centre it on its base plate
            uc = S.get("UC 254x254x73")
            m.section(f"column_{side}", "Column UC 254x254x73 holding up the runway", STRUCTURE,
                      "UC 254x254x73", run_z - 25, at=(x + uc["h"] / 2, y, 25), axis="z")
            m.box(f"base_plate_{side}", "Column base plate 500x500x25, anchored to the floor", DARK,
                  x - 250, x + 250, y - 250, y + 250, 0, 25)

    # roller bed: two RHS 120x80x5 rails on SHS 80x80x5 legs with foot plates; each roller is a 101.6x3.6 tube
    # on a 25 mm shaft in two pillow-block bearings (UCP205 class) bolted to the rails
    rr = M.ROLLER_R * mm
    bx0, bx1 = -300, M.WORK_LENGTH * mm + 300
    rail_top = bz - rr - 40
    for dy in (-400, 400):
        y = by + dy
        m.hollow("bed_rail", "Bed side rail RHS 120x80x5 S355 - carries the roller bearings", BED, 80, 120, 5,
                 (bx0, y, rail_top - 60), (bx1, y, rail_top - 60))
        for x in np.arange(bx0 + 150, bx1, 2000):
            m.hollow("bed_leg", "Bed leg SHS 80x80x5 S355", BED, 80, 80, 5, (x, y, 15), (x, y, rail_top - 120))
            m.box("bed_foot", "Leg foot plate 200x200x15, 4 x M12 anchors into the floor", DARK, x - 100, x + 100, y - 100, y + 100, 0, 15)
            for ax in (-70, 70):
                for ay in (-70, 70):
                    m.cyl("anchor", "Floor anchor M12 (resin or wedge)", STEEL, (x + ax, y + ay, 15), (x + ax, y + ay, 30), 9)
    for x in np.arange(bx0 + 150, bx1, 2000):
        m.hollow("bed_cross", "Bed cross member RHS 80x40x4 S355 - ties the two rails", BED, 80, 40, 4,
                 (x, by - 360, 300), (x, by + 360, 300))
    for x in M.ROLLER_X:
        X = x * mm
        m.tube("bed_roller", "Bed roller - tube 101.6x3.6, 720 long (top = bed height 900 mm)", ALU,
               (X, by - 360, bz - rr), (X, by + 360, bz - rr), rr, 3.6)
        for e in (-360, 357):
            m.cyl("roller_end", "Roller end cap with bearing seat", STEEL, (X, by + e, bz - rr), (X, by + e + 3, bz - rr), rr - 3.6)
        m.cyl("roller_shaft", "Roller shaft 25 mm, bright steel", STEEL, (X, by - 440, bz - rr), (X, by + 440, bz - rr), 12.5)
        for dy in (-400, 400):
            y = by + dy
            m.box("bearing_base", "Pillow-block bearing UCP205 - base", DARK, X - 70, X + 70, y - 19, y + 19, rail_top, rail_top + 15)
            m.cyl("bearing_housing", "Pillow-block bearing UCP205 - housing", DARK, (X, y - 17, bz - rr), (X, y + 17, bz - rr), 33)
            for bxo in (-52, 52):
                m.cyl("bearing_bolt", "M12 bolt - bearing to rail", STEEL, (X + bxo, y, rail_top + 15), (X + bxo, y, rail_top + 25), 9)
    # scrap tray under the bed
    tz = M.SCRAP_TRAY_Z * mm
    m.box("scrap_tray_floor", "Scrap tray - offcuts fall between the rollers into it", BLUE_TRAY,
          bx0, bx1, by - 300, by + 300, tz - 40, tz)
    for dy in (-300, 300):
        m.box("scrap_tray_side", "Scrap tray side", BLUE_TRAY, bx0, bx1, by + dy - 15, by + dy + 15, tz - 40, tz + 200)
    # outfeed table: RHS 100x50x4 frame on SHS 80x80x5 legs, decked with 60x10 flats on edge-spaced bearers
    ox0, ox1, oy0, oy1 = (v * mm for v in M.OUTFEED_DECK)
    for y in (oy0 + 50, oy1 - 50):
        m.hollow("outfeed_frame", "Outfeed table frame RHS 100x50x4 S355", BED, 50, 100, 4, (ox0, y, bz - 70), (ox1, y, bz - 70))
        for x in np.arange(ox0 + 100, ox1, 2000):
            m.hollow("outfeed_leg", "Outfeed table leg SHS 80x80x5 S355", BED, 80, 80, 5, (x, y, 15), (x, y, bz - 120))
            m.box("outfeed_foot", "Leg foot plate 200x200x15", DARK, x - 100, x + 100, y - 100, y + 100, 0, 15)
    for y in np.linspace(oy0 + 40, oy1 - 40, 6):
        m.box("outfeed_deck", "Outfeed table deck - 60x10 flat on edge-spaced runners; finished parts are put down here",
              GREEN, ox0, ox1, y - 30, y + 30, bz - 20, bz)

    # guarding: fence with an interlocked gate, light curtain at the infeed, desk, E-stop, stack light
    fx0, fx1, fy = (xa - 0.6) * mm, (xb + 0.6) * mm, W / 2 + 600
    runs = [(fx0, -fy, fx1, -fy, "gate"), (fx0, fy, fx1, fy, None), (fx0, -fy, fx0, fy, "curtain"), (fx1, -fy, fx1, fy, None)]
    gate_at = None
    for ax, ay, bx, byy, gap in runs:
        length = math.hypot(bx - ax, byy - ay)
        n = round(length / 2000)
        for i in range(n + 1):
            px, py = ax + (bx - ax) * i / n, ay + (byy - ay) * i / n
            m.box("fence_post", "Fence post 60x60 (BS EN ISO 14120 guard)", YELLOW, px - 30, px + 30, py - 30, py + 30, 0, 2100)
        for i in range(n):
            if gap == "gate" and i == n // 2:
                gate_at = (ax + (bx - ax) * i / n, ax + (bx - ax) * (i + 1) / n)
                continue
            if gap == "curtain" and i == 0:
                continue
            p0 = (ax + (bx - ax) * i / n, ay + (byy - ay) * i / n)
            p1 = (ax + (bx - ax) * (i + 1) / n, ay + (byy - ay) * (i + 1) / n)
            if abs(p1[1] - p0[1]) < 1:
                m.box("fence_mesh", "Weld-mesh fence panel 1900 high (BS EN ISO 13857 reach distances)", DARK,
                      p0[0] + 40, p1[0] - 40, p0[1] - 2, p0[1] + 2, 150, 2050)
            else:
                m.box("fence_mesh", "Weld-mesh fence panel 1900 high (BS EN ISO 13857 reach distances)", DARK,
                      p0[0] - 2, p0[0] + 2, min(p0[1], p1[1]) + 40, max(p0[1], p1[1]) - 40, 150, 2050)
    if gate_at:
        g0, g1 = gate_at
        w = g1 - g0 - 60
        # the gate is its own body: hinged at (g0 + 30, -fy), it swings when the interlock opens
        m.box("gate_frame", "Interlocked gate (BS EN ISO 14119): opening it stops the machine", YELLOW,
              0, w, -25, 25, 150, 200, group="gate")
        m.box("gate_frame", "Interlocked gate", YELLOW, 0, w, -25, 25, 2000, 2050, group="gate")
        m.box("gate_frame", "Interlocked gate", YELLOW, w - 50, w, -25, 25, 150, 2050, group="gate")
        m.box("gate_mesh", "Interlocked gate mesh", DARK, 0, w - 50, -2, 2, 200, 2000, group="gate")
        m.box("gate_switch", "Gate interlock switch (coded, with guard locking)", RED, w - 100, w - 40, -60, -25, 1050, 1170, group="gate")
        m.gate_hinge = (g0 + 30, -fy)
        gx = (g0 + g1) / 2
    else:
        gx = 6000
        m.gate_hinge = (gx, -fy)
    cy1 = -fy + 2 * fy / round(2 * fy / 2000)
    for y in (-fy + 50, cy1 - 50):
        m.box("light_curtain", "Light curtain post (Type 4, BS EN IEC 61496) across the infeed opening", RUBBER,
              fx0 - 150, fx0 - 90, y - 30, y + 30, 0, 1800)
    m.box("desk", "Operator desk - the Jetson and the screen", DARK, gx + 2000, gx + 3200, -fy - 1400, -fy - 800, 0, 900)
    m.box("screen", "Operator screen", RUBBER, gx + 2250, gx + 2950, -fy - 1040, -fy - 1000, 1050, 1470)
    m.box("estop_box", "Emergency stop (BS EN ISO 13850) - red mushroom on yellow", YELLOW,
          gx + 2090, gx + 2210, -fy - 1110, -fy - 990, 900, 980)
    m.cyl("estop_head", "Emergency stop button", RED, (gx + 2150, -fy - 1050, 980), (gx + 2150, -fy - 1050, 1020), 45)
    m.box("camera_mast", "Camera mast - the YOLO camera watches the gate and the cell", DARK,
          gx - 1630, gx - 1570, -fy - 430, -fy - 370, 0, 3000)
    m.box("camera", "Safety-zone camera (USB / CSI) on the Jetson", RUBBER, gx - 1680, gx - 1520, -fy - 370, -fy - 270, 2900, 3000)
    # sensors that find the bar, and watch for fire and people (see beamcell/sensors.py)
    m.box("end_stop", "Bar end stop at the infeed end - the datum the bar is put against", DARK,
          -470, -400, by - 120, by + 120, 0, bz + 120)
    m.box("datum_laser", "Datum laser (SICK DT50 class) on the end stop - measures where the bar really starts", RED,
          -400, -330, by - 35, by + 35, bz + 40, bz + 110)
    for dy, what in ((-460, "sender"), (460, "receiver")):
        m.box("bar_eye", f"Bar-present photo-eye ({what}) - a bar is on the bed", DARK,
              150, 210, by + dy - 30, by + dy + 30, bz + 20, bz + 120)
    fdx, fdy = xa * mm + 4000, -W / 2 * mm - 250
    m.box("fire_detector_bracket", "Detector bracket (angle) bolted to the column", DARK, fdx - 20, fdx + 20, fdy - 20, fdy + 260, run_z - 60, run_z - 40)
    m.cyl("fire_detector", "Flame detector (UV/IR, e.g. Honeywell FS24X class) - watches the bed and scrap tray", (0.9, 0.9, 0.88),
          (fdx, fdy + 260, run_z - 60), (fdx, fdy + 260, run_z - 160), 55)
    m.cyl("fire_detector_window", "Flame detector window", RUBBER, (fdx, fdy + 260, run_z - 160), (fdx, fdy + 260, run_z - 175), 35)
    for fx in (fx0 + 250, fx1 - 250):
        m.box("area_scanner", "Safety laser scanner (SICK microScan3 class, PL d) - watches the cell floor", YELLOW,
              fx - 80, fx + 80, -fy + 120, -fy + 280, 0, 180)
    m.box("stack_pole", "Stack light pole", DARK, gx + 3330, gx + 3370, -fy - 1020, -fy - 980, 900, 2100)
    for i, (lamp, colour) in enumerate((("red", (1, 0.16, 0.12)), ("amber", (1, 0.69, 0)), ("green", (0.13, 0.83, 0.42)), ("blue", (0.18, 0.48, 1)))):
        z = 2600 - i * 120
        m.cyl(f"lamp_{lamp}", f"Stack light - {lamp}", colour, (gx + 3350, -fy - 1000, z - 55), (gx + 3350, -fy - 1000, z + 55), 60)

    # power and signals: control cabinet, plasma power source, trunking, risers and the energy-chain trays
    # (the chains themselves move with the bridges: web/js/cables.js)
    rz = M.RAIL_Z * mm
    x_fix = (xa + xb) / 2 * mm                                   # each runway chain is fixed at the middle of the travel
    # control cabinet (floor-standing enclosure, 1200 x 600 x 2000 on a 100 plinth)
    cx0, cy0 = gx + 3700, -fy - 1500
    GREY = (0.80, 0.81, 0.82)
    m.box("cabinet_plinth", "Cabinet plinth 100 mm", DARK, cx0, cx0 + 1200, cy0 + 20, cy0 + 580, 0, 100)
    m.box("control_cabinet", "Control cabinet - servo drives, safety PLC, contactors, the Jetson's I/O (1200x600x2000)", GREY,
          cx0, cx0 + 1200, cy0, cy0 + 600, 100, 2100)
    for k, (d0, d1) in enumerate(((cx0 + 5, cx0 + 597), (cx0 + 603, cx0 + 1195))):
        m.box("cabinet_door", "Cabinet door", (0.74, 0.75, 0.77), d0, d1, cy0 - 18, cy0, 110, 2090)
        hx = d1 - 60 if k == 0 else d0 + 60
        m.box("cabinet_handle", "Door handle (lockable)", DARK, hx - 15, hx + 15, cy0 - 45, cy0 - 18, 1000, 1160)
        for z in (300, 360, 420):
            m.box("cabinet_vent", "Filter fan grille", DARK, (d0 + d1) / 2 - 120, (d0 + d1) / 2 + 120, cy0 - 22, cy0 - 18, z, z + 30)
    m.box("isolator", "Main isolator - lockable rotary handle (PUWER reg 19, BS EN 60204-1)", RED,
          cx0 + 1060, cx0 + 1160, cy0 - 50, cy0 - 18, 1500, 1600)
    m.box("isolator_plate", "Isolator mounting plate", YELLOW, cx0 + 1040, cx0 + 1180, cy0 - 20, cy0 - 18, 1480, 1620)
    # plasma power source + gas console (Hypertherm XPR class proportions) and the gas supply
    px = cx0 + 1200 + 700                                         # 700 mm clear beside the cabinet
    py0 = -fy - 1500
    m.box("plasma_power_source", "Plasma power source (Hypertherm XPR300 class) - 400 V 3-phase, own coolant", GREY,
          px, px + 600, py0, py0 + 1100, 120, 1250)
    m.box("plasma_front", "Plasma power source front panel", RED, px + 20, px + 580, py0 - 8, py0, 600, 1230)
    m.box("plasma_display", "Status display", RUBBER, px + 200, px + 400, py0 - 12, py0 - 8, 1050, 1150)
    for cxw in (px + 60, px + 540):
        for cyw in (py0 + 80, py0 + 1020):
            m.cyl("castor", "Castor", RUBBER, (cxw, cyw - 30, 60), (cxw, cyw + 30, 60), 60)
    for hy in (py0 + 150, py0 + 950):
        m.cyl("lifting_eye", "Lifting eye", STEEL, (px + 300, hy, 1250), (px + 300, hy, 1290), 18)
    m.box("plasma_gas_console", "Plasma gas console - O2 / air / N2 metering to the torch", (0.86, 0.87, 0.88),
          px + 50, px + 550, py0 + 200, py0 + 800, 1250, 1600)
    for rx in (px + 1000, px + 1720):                              # cylinder rack: two posts, two chains, base
        m.hollow("gas_rack", "Cylinder rack post SHS 50x50x3, bolted to the floor", YELLOW, 50, 50, 3,
                 (rx, py0 + 440, 0), (rx, py0 + 440, 1300))
    for z in (700, 1150):
        m.box("gas_rack_chain", "Cylinder restraint chain", STEEL, px + 1000, px + 1720, py0 + 425, py0 + 435, z, z + 25)
    for i, (col, gas) in enumerate((((0.95, 0.95, 0.95), "oxygen (white shoulder)"), ((0.15, 0.15, 0.15), "nitrogen (black)"),
                                     ((0.95, 0.95, 0.95), "oxygen (white shoulder)"))):
        cxg = px + 1120 + i * 240
        m.cyl("gas_cylinder", f"Gas cylinder 50 l - {gas}", (0.35, 0.35, 0.38) if i != 1 else (0.15, 0.15, 0.15),
              (cxg, py0 + 280, 0), (cxg, py0 + 280, 1450), 115)
        m.cyl("gas_cylinder_shoulder", f"Cylinder shoulder - {gas}", col, (cxg, py0 + 280, 1450), (cxg, py0 + 280, 1560), 115, r1=40)
        m.cyl("gas_valve", "Cylinder valve and regulator", (0.75, 0.6, 0.2), (cxg, py0 + 280, 1560), (cxg, py0 + 280, 1660), 22)
    cols = [(xa + i * (xb - xa) / math.ceil((xb - xa) / 4.0)) * mm for i in range(math.ceil((xb - xa) / 4.0) + 1)]
    xc = min(cols, key=lambda x: abs(x - x_fix))                 # the column nearest the chains' fixed point
    def floor_trunk(x0_, x1_, y0_, y1_, label):
        """Walk-over floor trunking: a steel base, two sides and a chequer-plate lid."""
        m.box("floor_trunking", label, DARK, x0_, x1_, y0_, y1_, 0, 5)
        m.box("floor_trunking_lid", "Trunking lid - chequer plate, walk-over", STEEL, x0_, x1_, y0_, y1_, 70, 76)
        along_x = (x1_ - x0_) > (y1_ - y0_)
        for k in (0, 1):
            if along_x:
                yy = y0_ if k == 0 else y1_ - 4
                m.box("floor_trunking", label, DARK, x0_, x1_, yy, yy + 4, 0, 70)
            else:
                xx = x0_ if k == 0 else x1_ - 4
                m.box("floor_trunking", label, DARK, xx, xx + 4, y0_, y1_, 0, 70)
    floor_trunk(min(gx + 3700, xc) - 50, max(px + 600, xc + 50), -fy - 680, -fy - 520,
                "Floor trunking - power, signals, torch lead, gas hoses")
    floor_trunk(xc + 250, xc + 400, -fy - 680, W / 2 + 200, "Floor trunking under the bed to the back runway (Handler)")
    for side in (-1, 1):
        y_tray = side * (W / 2 + 350)
        m.box("riser", "Cable riser up the column to the energy-chain tray", DARK,
              xc + 250, xc + 400, side * (W / 2 + 60) - 70, side * (W / 2 + 60) + 70, 0, rz - 80)
        m.box("riser", "Cable riser up the column to the energy-chain tray", DARK,
              xc + 250, xc + 400, min(side * (W / 2 + 60), y_tray) - 70, max(side * (W / 2 + 60), y_tray) + 70, rz - 130, rz - 80)
        who = "Cutter (torch lead, gas hoses, servo cables)" if side < 0 else "Handler (magnet power, servo cables)"
        m.box("chain_tray", f"Energy-chain tray along the runway - the {who} chain lies in it", STEEL,
              x0, x_fix + 400, y_tray - 85, y_tray + 85, rz - 110, rz - 100)
        for wall in (-1, 1):
            m.box("chain_tray", "Energy-chain tray side", STEEL, x0, x_fix + 400, y_tray + wall * 85 - 4, y_tray + wall * 85 + 4, rz - 110, rz - 20)
        for xb_ in np.arange(x0 + 500, x_fix + 400, 2000):
            m.box("tray_bracket", "Tray bracket bolted to the runway", DARK, xb_ - 30, xb_ + 30,
                  min(side * W / 2, y_tray) - 90, max(side * W / 2, y_tray) + 90, rz - 140, rz - 110)

    # the two hands: each body in its own frame, posed by the 3D view
    for hand in M.make_hands():
        _hand_bodies(m, hand)
    return m


def _hand_bodies(m, hand):
    """Bridge, carriage, mast and arm links of one hand. Each body is modelled in its own frame:
         bridge   at (gantry x, 0, rail z)          carriage  at (gantry x, gantry y, rail z)
         mast     at the arm base (gantry x, y, z)  link k    in DH frame k of the arm (k = 0..6)
    """
    key = hand.name.lower()
    W = M.WIDTH * 1000
    paint = tuple(int(hand.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    g = f"{key}.bridge"
    # bridge: box girder spanning the rails, end trucks with wheels, drive motors
    m.box("bridge_girder", f"{hand.name} bridge - box girder spanning both rails", YELLOW, -160, 160, -W / 2 - 250, W / 2 + 250, 90, 510, group=g)
    m.box("bridge_cover", f"{hand.name} bridge - cable tray on top", DARK, -170, 170, -W / 2 - 260, W / 2 + 260, 510, 540, group=g)
    for y in (-W / 2, W / 2):
        m.box("end_truck", f"{hand.name} end truck", YELLOW, -450, 450, y - 120, y + 120, -40, 200, group=g)
        # the wheels stand on the crane rail, whose top is a little below the bridges' rail height
        wz = CRANE_RAIL_TOP - M.RAIL_Z * 1000 + 90
        for dx in (-320, 320):
            m.cyl("wheel", "Crane wheel 180 dia", RUBBER, (dx, y - 40, wz), (dx, y + 40, wz), 90, group=g)
        ys = -180 if y > 0 else 180
        m.cyl("drive_motor", f"{hand.name} long-travel motor + gearbox (X axis)", DARK, (300, y + ys, 120), (520, y + ys, 120), 80, group=g)
    # carriage on the bridge (Y axis), with its motor
    g = f"{key}.carriage"
    m.box("carriage", f"{hand.name} carriage - runs across the bridge (Y axis)", DARK, -310, 310, -250, 250, -180, 180, group=g)
    m.box("carriage_band", f"{hand.name} carriage", paint, -315, 315, -255, 255, -180, -120, group=g)
    m.cyl("carriage_motor", f"{hand.name} cross-travel motor (Y axis)", RUBBER, (0, 0, 180), (0, 0, 480), 85, group=g)
    m.cyl("mast_motor", f"{hand.name} lift motor (Z axis)", RUBBER, (200, 150, 180), (200, 150, 420), 70, group=g)
    if hand.tool == "torch":
        m.box("profile_scanner", "Laser profile scanner (Micro-Epsilon scanCONTROL class) - measures the real bar as the Cutter passes",
              DARK, 320, 440, -70, 70, -230, -110, group=g)
    # mast: slides up and down through the carriage (Z axis); the arm hangs under it
    g = f"{key}.mast"
    m.box("mast", f"{hand.name} mast 200x200 - slides through the carriage (Z axis)", paint, -100, 100, -100, 100, 0, 2000, group=g)
    m.box("mast_rack", f"{hand.name} mast rack and guide", DARK, 100, 115, -40, 40, 50, 1950, group=g)
    m.box("arm_flange", f"{hand.name} arm mounting flange", DARK, -140, 140, -140, 140, -30, 0, group=g)
    # arm links in their own DH frames: link k joins joint k (the previous frame) to frame k
    arm = hand.arm
    sc = abs(arm.a[1]) / 0.425 if arm.a[1] else 1.0
    r = 55 * sc
    frames0 = arm.frames(np.zeros(6))
    for k in range(7):
        grp = f"{key}.link{k}"
        rr = r * (1.35 if k < 3 else 1.0)
        # the motor housing of the NEXT joint sits at this frame's origin, along its z axis
        if k < 6:
            m.cyl("joint", f"{hand.name} arm - joint {k + 1} motor and gearbox", DARK if k % 2 == 0 else paint,
                  (0, 0, -rr * 1.15), (0, 0, rr * 1.15), rr, group=grp)
        if k >= 1:
            prev = np.linalg.inv(frames0[k]) @ np.append(frames0[k - 1][:3, 3], 1.0)       # joint k in frame k
            a = prev[:3] * 1000
            if np.linalg.norm(a) > 1:
                m.cyl("link", f"{hand.name} arm - link {k}", paint, a, (0, 0, 0), r * (1.0 if k < 4 else 0.75), group=grp)
    # tool on frame 6, pointing along z
    grp = f"{key}.link6"
    T = arm.tool_length * 1000
    if hand.tool == "torch":
        m.cyl("torch_body", "Plasma torch (machine torch, 400 mm)", RUBBER, (0, 0, 0), (0, 0, T - 40), 22, group=grp)
        m.cyl("torch_sleeve", "Torch holder with crash sensor", DARK, (0, 0, 0), (0, 0, 60), 32, group=grp)
        m.cyl("torch_nozzle", "Plasma nozzle and shield cup", (0.72, 0.45, 0.2), (0, 0, T - 40), (0, 0, T), 16, group=grp, r1=6)
        m.box("torch_camera", "Camera 2 - close-up on the torch: bar edges, cut line, hole quality, nozzle wear", DARK,
              30, 90, -25, 25, 70, 140, group=grp)
    else:
        m.cyl("magnet_stem", "Magnet stem with load cell", DARK, (0, 0, 0), (0, 0, T - 30), 30, group=grp)
        m.cyl("magnet_pad", "Lifting magnet (battery-backed, BS EN 13155) - 500 kg", RED, (0, 0, T - 30), (0, 0, T), 110, group=grp)


def export_cell():
    """Both machine sizes: 12 m -> cad/beam_cell.step, web/models/cell.glb + labels.json;
    20 m -> beam_cell_20m.step, cell_20m.glb + labels_20m.json. moving.glb is the same for both."""
    was = M.WORK_LENGTH
    out = []
    try:
        for length in M.LENGTHS:
            M.set_length(length)
            out += _export_cell("" if length == 12 else f"_{length:g}m")
    finally:
        M.set_length(was)
    return out


def _export_cell(suffix):
    m = build_cell()
    os.makedirs(CAD_DIR, exist_ok=True)
    os.makedirs(WEB_MODELS, exist_ok=True)
    # GLB for the 3D view (metres): the static cell, and one file with every moving body in its own frame
    exportGLTF(m.assembly(scale=0.001), os.path.join(WEB_MODELS, f"cell{suffix}.glb"), binary=True, tolerance=0.002, angularTolerance=0.35)
    moving = sorted({it[0] for it in m.items if it[0]})
    exportGLTF(m.assembly(scale=0.001, groups=moving), os.path.join(WEB_MODELS, "moving.glb"), binary=True,
               tolerance=0.001, angularTolerance=0.3)
    import json
    with open(os.path.join(WEB_MODELS, f"labels{suffix}.json"), "w") as fh:
        json.dump({"labels": m.labels(), "gate_hinge_m": [v / 1000 for v in m.gate_hinge]}, fh, indent=0, sort_keys=True)
    # STEP (mm): the whole cell with both hands posed at park, as one assembly
    step = m.assembly()
    for hand in M.make_hands():
        key = hand.name.lower()
        gpos = hand.park * 1000
        q = _hand_rest(hand)
        frames = hand.world_frames(hand.park, q)
        places = {f"{key}.bridge": _loc(np.eye(3), (gpos[0], 0, M.RAIL_Z * 1000)),
                  f"{key}.carriage": _loc(np.eye(3), (gpos[0], gpos[1], M.RAIL_Z * 1000 - 120)),
                  f"{key}.mast": _loc(np.eye(3), gpos)}
        for k in range(7):
            places[f"{key}.link{k}"] = _loc(frames[k][:3, :3], frames[k][:3, 3] * 1000)
        for grp, loc in places.items():
            sub = m.assembly(groups=[grp])
            step.add(sub, name=grp.replace(".", "_"), loc=loc)
    gate = m.assembly(groups=["gate"])
    step.add(gate, name="gate", loc=_loc(np.eye(3), (m.gate_hinge[0], m.gate_hinge[1], 0)))
    path = os.path.join(CAD_DIR, f"beam_cell{suffix}.step")
    step.export(path)
    return [path, os.path.join(WEB_MODELS, f"cell{suffix}.glb"), os.path.join(WEB_MODELS, "moving.glb")]


def _loc(R, t):
    """cq.Location from a rotation matrix and a translation (mm)."""
    R = np.asarray(R, float)
    angle = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1) / 2)))
    if angle < 1e-9:
        return cq.Location(cq.Vector(*map(float, t)))
    if abs(angle - math.pi) < 1e-6:
        axis = np.sqrt(np.maximum((np.diag(R) + 1) / 2, 0))
        i = int(np.argmax(axis))
        for j in range(3):
            if j != i and R[i, j] < 0:
                axis[j] = -axis[j]
    else:
        axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * math.sin(angle))
    return cq.Location(cq.Vector(*map(float, t)), cq.Vector(*map(float, axis)), math.degrees(angle))


# ======================================================================= the 1:10 working prototype
PROTO_SCALE = 0.1               # 1:10
PROTO_LENGTH = 600.0            # mm of bed (= a 6 m bar at full size); make it 1200 for the full 12 m


def build_prototype():
    """A 1:10 desk-top prototype made from parts you can buy (see docs/PROTOTYPE.md): 20x20 aluminium
    T-slot frame, NEMA 17 motors on GT2 belts and T8 lead screws, two MeArm-size 4-servo arms on a
    PCA9685 board, a pen 'torch' and a small 5 V electromagnet. Labels say what to buy or print."""
    need_cadquery()
    s = PROTO_SCALE
    m = Model("beam_cell_prototype_1to10")
    Lx = PROTO_LENGTH + 300                                  # rails run past the bed so the bridges can park
    x0 = -150.0
    W = M.WIDTH * 1000 * s                                   # 300 between rail centres
    rail_z = M.RAIL_Z * 1000 * s                             # 340
    bz = M.BED_Z * 1000 * s                                  # 90
    by = M.BEAM_Y * 1000 * s                                 # -50
    E = "20x20 V-slot aluminium extrusion"
    # base frame on the table, uprights, top rails (all 20x20)
    for y in (-W / 2, W / 2):
        m.extrusion("base_rail", f"{E} - base rail {Lx:.0f} mm", ALU, (20, 20), (x0, y, 10), (x0 + Lx, y, 10))
        m.extrusion("top_rail", f"{E} - gantry rail {Lx:.0f} mm (the bridges' wheels run on it)", ALU, (20, 20),
                    (x0, y, rail_z - 10), (x0 + Lx, y, rail_z - 10))
        for x in (x0 + 10, x0 + Lx / 2, x0 + Lx - 10):
            m.extrusion("upright", f"{E} - upright {rail_z - 40:.0f} mm", ALU, (20, 20), (x, y, 20), (x, y, rail_z - 20))
    for x in (x0 + 10, x0 + Lx - 10):
        for z in (10, rail_z - 10):
            m.extrusion("cross_member", f"{E} - cross member {W - 20:.0f} mm", ALU, (20, 20), (x, -W / 2 + 10, z), (x, W / 2 - 10, z))
    # roller bed: two 20x20 rails on printed risers, 10 mm rollers every 100 mm (= 1 m full size)
    for dy in (-30, 30):
        m.extrusion("bed_rail", f"{E} - bed rail {PROTO_LENGTH + 100:.0f} mm", ALU, (20, 20),
                    (-50, by + dy, bz - 20), (PROTO_LENGTH + 50, by + dy, bz - 20))
        for x in (-40, PROTO_LENGTH / 2, PROTO_LENGTH + 40):
            m.box("bed_riser", "Bed riser block (3D printed) - holds the bed rails on the base", PRINTED,
                  x - 10, x + 10, by + dy - 10, by + dy + 10, 0, bz - 30)
    for x in (50 + 100 * i for i in range(int(PROTO_LENGTH / 100))):
        m.cyl("bed_roller", "Bed roller: 10 mm printed sleeve on a 3 mm steel rod, 2 x 623 bearings", ALU,
              (x, by - 25, bz - 5), (x, by + 25, bz - 5), 5)
        for dy in (-30, 30):
            m.box("bed_bracket", "Roller bracket (3D printed, PETG) - clips on the bed rail", PRINTED,
                  x - 6, x + 6, by + dy - 10, by + dy + 10, bz - 10, bz - 2)
    m.box("scrap_tray", "Scrap tray (3D printed) - offcuts fall into it", BLUE_TRAY, -50, PROTO_LENGTH + 50, by - 22, by + 22, 20, 24)
    oy0, oy1 = M.OUTFEED_DECK[2] * 1000 * s, M.OUTFEED_DECK[3] * 1000 * s
    m.box("outfeed_table", "Outfeed table: 3 mm plywood strip on printed risers", GREEN, -50, PROTO_LENGTH + 50, oy0, oy1, bz - 3, bz)
    for x in (-40, PROTO_LENGTH / 2, PROTO_LENGTH + 40):
        m.box("outfeed_riser", "Outfeed table riser (3D printed)", PRINTED, x - 10, x + 10, (oy0 + oy1) / 2 - 10, (oy0 + oy1) / 2 + 10, 0, bz - 3)
    # model beam on the bed: a 3D-printed UB 305x165 at 1:10 (30 x 16 mm), walls thickened to print
    ub = S.get("UB 305x165x40")
    tiny = dict(ub, h=ub["h"] * s, b=ub["b"] * s, tw=max(ub["tw"] * s, 1.2), tf=max(ub["tf"] * s, 1.2), r=ub["r"] * s)
    m.add("model_beam", "Model beam: UB 305x165x40 at 1:10 (30 x 16 mm), 3D printed, steel tape on top", section_solid(tiny, PROTO_LENGTH - 100).translate((10, by, bz)), STEEL)
    # each hand: bridge (20x20 on mini V-wheel plates), carriage plate, Z axis (20x20 + T8 screw), arm, tool
    for hand, hx in ((M.make_hands()[1], 50.0), (M.make_hands()[0], 450.0)):
        name = hand.name
        paint = tuple(int(hand.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        # bridge ends: a mini V-wheel gantry plate lies flat 6 mm above each top rail and its four
        # V-wheels clamp the rail from both sides, running in the rail's side slots (wheel axes upright)
        top = rail_z + 9                                     # top of the gantry plates = underside of the bridge
        m.extrusion("bridge", f"{name} bridge: {E} {W + 40:.0f} mm", ALU, (20, 20), (hx, -W / 2 - 20, top + 10), (hx, W / 2 + 20, top + 10), use="bridge")
        for y in (-W / 2, W / 2):
            m.box("gantry_plate", f"{name} bridge end: mini V-wheel gantry plate (20 series), clamps the gantry rail",
                  DARK, hx - 30, hx + 30, y - 26, y + 26, top - 3, top)
            for dx in (-18, 18):
                for dy in (-15.6, 15.6):                     # 10 mm half-rail + 7.6 wheel radius - 2 mm into the slot
                    m.cyl("v_wheel", "Mini V-wheel (625 bearing) on an eccentric spacer - runs in the rail's side slot",
                          RUBBER, (hx + dx, y + dy, rail_z - 14.4), (hx + dx, y + dy, rail_z - 5.6), 7.6)
                    m.cyl("wheel_spacer", "Eccentric spacer + M5 bolt: holds the V-wheel under the gantry plate",
                          STEEL, (hx + dx, y + dy, rail_z - 5.6), (hx + dx, y + dy, top - 3), 3.5)
        m.box("x_motor", f"{name} X motor: NEMA 17 driving both rails through a 5 mm cross shaft and GT2 belts",
              RUBBER, hx + 14, hx + 56, -W / 2 + 25, -W / 2 + 65, top + 20, top + 62)
        m.cyl("cross_shaft", "5 mm cross shaft with GT2 16T pulleys at both ends", STEEL, (hx + 35, -W / 2, top + 30), (hx + 35, W / 2, top + 30), 2.5)
        # carriage: a mini V-wheel plate standing on the bridge's side face, wheels running in the
        # bridge's top and bottom slots; the Z axis, both motors and the arm hang off its outer face
        cy = 0.0
        bz0, bz1 = top, top + 20                             # the bridge extrusion
        m.box("carriage_plate", f"{name} carriage: mini V-wheel gantry plate on the side of the bridge (Y axis)",
              DARK, hx - 19, hx - 16, cy - 30, cy + 30, bz0 - 14, bz1 + 14)
        for dy in (-18, 18):
            for wz in (bz0 - 5.6, bz1 + 5.6):
                m.cyl("v_wheel", "Mini V-wheel (625 bearing) - runs in the bridge's top / bottom slot",
                      RUBBER, (hx - 16, cy + dy, wz), (hx - 7.2, cy + dy, wz), 7.6)
        zx = hx - 29                                         # Z axis centre, bolted to the carriage plate
        shelf = bz1 + 14
        m.box("z_motor_mount", f"{name} motor shelf (3D printed): holds the Z and Y motors on top of the carriage plate",
              PRINTED, hx - 63, hx - 16, cy - 58, cy + 58, shelf, shelf + 3)
        m.box("y_motor", f"{name} Y motor: NEMA 17 + GT2 belt along the bridge", RUBBER,
              hx - 61, hx - 19, cy - 56, cy - 14, shelf + 3, shelf + 43)
        m.box("z_motor", f"{name} Z motor: NEMA 17 with integrated T8 x 2 mm lead screw (150 mm)", RUBBER,
              hx - 61, hx - 19, cy + 14, cy + 56, shelf + 3, shelf + 43)
        z_len = 200.0
        beam_top = bz + tiny["h"]
        tool = 150 if hand.tool == "torch" else 130          # arm base to tool tip in this pose
        zb = beam_top + (5 if hand.tool == "torch" else 0) + tool
        m.extrusion("z_axis", f"{name} Z axis: {E} {z_len:.0f} mm on a T8 lead screw (slides on the carriage plate)", ALU,
                    (20, 20), (zx, cy, zb), (zx, cy, zb + z_len), use="Z axis")
        m.cyl("lead_screw", "T8 x 2 mm lead screw, 150 mm", STEEL, (hx - 40, cy + 35, shelf), (hx - 40, cy + 35, zb + 20), 4)
        m.box("lead_nut", f"{name} lead-screw nut block on the Z axis (3D printed + brass T8 nut)", PRINTED,
              hx - 52, hx - 28, cy + 10, cy + 47, zb + 20, zb + 32)
        m.box("arm_mount", f"{name} arm mount plate (3D printed)", PRINTED, zx - 22, zx + 22, cy - 22, cy + 22, zb - 4, zb)
        # MeArm-size 4-servo arm (MG90S micro servos) hanging under the Z axis
        m.cyl("arm_base", f"{name} arm: MeArm-type 4-servo arm kit (MG90S servos) - base", paint, (zx, cy, zb - 4), (zx, cy, zb - 30), 22)
        m.box("arm_upper", f"{name} arm: upper arm (~80 mm)", paint, zx - 8, zx + 8, cy - 8, cy + 8, zb - 95, zb - 30)
        m.box("arm_fore", f"{name} arm: forearm (~80 mm)", paint, zx - 6, zx + 70, cy - 6, cy + 6, zb - 108, zb - 95)
        m.box("arm_wrist", f"{name} arm: wrist / tool holder", paint, zx + 60, zx + 80, cy - 9, cy + 9, zb - 120, zb - 108)
        if hand.tool == "torch":
            m.cyl("pen_tool", "Cutter 'torch' for the prototype: fine-liner pen in a sprung 3D-printed holder (marks the cut lines)",
                  RUBBER, (zx + 70, cy, zb - 120), (zx + 70, cy, zb - 150), 4)
        else:
            m.cyl("magnet_tool", "Handler magnet: 5 V 20 mm lifting electromagnet (holds about 2.5 kg)", RED,
                  (zx + 70, cy, zb - 120), (zx + 70, cy, zb - 130), 10)
    # electronics and safety beside the frame
    m.box("control_box", "Control box: Jetson Orin Nano, FluidNC 6-axis board, PCA9685 servo board, 24 V and 5 V supplies, fuses, safety relay",
          DARK, x0 + Lx + 20, x0 + Lx + 180, -100, 100, 0, 110)
    m.box("estop", "Emergency stop: 40 mm red mushroom, 2 NC contacts, yellow box (BS EN ISO 13850)", YELLOW,
          x0 + Lx + 40, x0 + Lx + 110, -W / 2 - 80, -W / 2 - 10, 0, 70)
    m.cyl("estop_head", "Emergency stop head", RED, (x0 + Lx + 75, -W / 2 - 45, 70), (x0 + Lx + 75, -W / 2 - 45, 95), 20)
    m.box("enclosure_front", "Enclosure door: 2 mm polycarbonate on a 20x20 frame, with a safety interlock switch", (0.8, 0.85, 0.9),
          x0 + 100, x0 + Lx - 100, -W / 2 - 22, -W / 2 - 20, 20, rail_z - 20)
    m.box("door_switch", "Door interlock switch (magnetic coded, NC) - opens = protective stop", RED,
          x0 + Lx - 115, x0 + Lx - 100, -W / 2 - 36, -W / 2 - 22, 150, 180)
    m.box("camera", "Camera: USB wide-angle (or IMX219 CSI) on a 20x20 post - YOLO watches the cell", RUBBER,
          x0 - 60, x0 - 20, -W / 2 - 20, -W / 2 + 20, rail_z + 60, rail_z + 100)
    m.extrusion("camera_post", f"{E} - camera post", ALU, (20, 20), (x0 - 40, -W / 2, 10), (x0 - 40, -W / 2, rail_z + 60))
    # sensors (see beamcell/sensors.py and the Sensors tab): find the bar, check the tools, watch for fire
    m.box("tof_sensor", "Datum sensor: VL53L1X time-of-flight at the bed's infeed end - finds where the model beam starts", RED,
          -48, -40, by - 8, by + 8, bz + 2, bz + 18)
    for dy in (-38, 38):
        m.box("break_beam", "Bar-present IR break-beam (one each side of the bed)", RUBBER, 20, 26, by + dy - 3, by + dy + 3, bz, bz + 12)
    m.box("flame_sensor", "IR flame sensor module (demo of the fire detector)", RED, x0 - 52, x0 - 28, -W / 2 + 10, -W / 2 + 22, rail_z + 30, rail_z + 46)
    for hand, hx in ((M.make_hands()[1], 50.0), (M.make_hands()[0], 450.0)):
        zx, cy = hx - 29, 0.0
        zb = bz + tiny["h"] + (5 + 150 if hand.tool == "torch" else 130)
        if hand.tool == "torch":
            m.box("torch_camera", "Camera 2: IMX219 close-up beside the pen - the cut line, the bar edge", RUBBER,
                  zx + 52, zx + 60, cy - 12, cy - 4, zb - 132, zb - 120)
            m.box("line_laser", "Line laser (Class 2) - with camera 2 it shows the beam's real profile", RED,
                  zx + 52, zx + 60, cy + 4, cy + 12, zb - 132, zb - 122)
            m.box("pen_switch", "Pen touch-off micro-switch on the sprung holder - finds the beam's surface", DARK,
                  zx + 74, zx + 84, cy - 5, cy + 5, zb - 126, zb - 120)
        else:
            m.box("load_cell", "Load cell (1 kg) between wrist and magnet - weighs the part: slipping, wrong part, not cut free", ALU,
                  zx + 62, zx + 78, cy - 7, cy + 7, zb - 106, zb - 101)
    return m


# which shopping-list line (docs/prototype_bom.csv) each solid in the prototype is
PROTO_PARTS = {
    "base_rail": "V-slot 20x20 aluminium extrusion", "top_rail": "V-slot 20x20 aluminium extrusion",
    "upright": "V-slot 20x20 aluminium extrusion", "cross_member": "V-slot 20x20 aluminium extrusion",
    "bed_rail": "V-slot 20x20 aluminium extrusion", "z_axis": "V-slot 20x20 aluminium extrusion",
    "camera_post": "V-slot 20x20 aluminium extrusion", "bridge": "V-slot 20x20 aluminium extrusion",
    "bed_roller": "Bed rollers", "bed_bracket": "Roller brackets (3D printed)", "bed_riser": "Bed riser blocks (3D printed)",
    "outfeed_table": "Outfeed table board", "outfeed_riser": "Outfeed table risers (3D printed)",
    "scrap_tray": "Scrap tray (3D printed)", "model_beam": "Model beams (3D printed)",
    "gantry_plate": "Mini V-wheel gantry plate kits", "carriage_plate": "Mini V-wheel gantry plate kits",
    "v_wheel": "Mini V-wheel gantry plate kits", "wheel_spacer": "Mini V-wheel gantry plate kits",
    "x_motor": "NEMA 17 stepper motor", "y_motor": "NEMA 17 stepper motor",
    "z_motor": "NEMA 17 with integrated T8 lead screw", "lead_screw": "NEMA 17 with integrated T8 lead screw",
    "z_motor_mount": "Z motor bracket (3D printed)", "lead_nut": "Lead-screw nut block (3D printed)",
    "cross_shaft": "5 mm cross shafts + bearings",
    "arm_mount": "Arm mount plate (3D printed)",
    "arm_base": "MeArm-type 4-servo arm kit", "arm_upper": "MeArm-type 4-servo arm kit",
    "arm_fore": "MeArm-type 4-servo arm kit", "arm_wrist": "MeArm-type 4-servo arm kit",
    "pen_tool": "Cutter 'torch' for the prototype (pen holder)", "magnet_tool": "Handler magnet",
    "control_box": "Control box", "estop": "Emergency stop station", "estop_head": "Emergency stop station",
    "enclosure_front": "Polycarbonate sheet 2 mm", "door_switch": "Door interlock switch",
    "camera": "USB wide-angle camera (safety zone)",
    "torch_camera": "CSI camera (close-up of the Cutter)", "break_beam": "IR break-beam sensor pair",
    "tof_sensor": "VL53L1X time-of-flight distance sensor", "pen_switch": "Pen touch-off micro-switch",
    "load_cell": "Load cell 1 kg + HX711", "flame_sensor": "IR flame sensor module", "line_laser": "Line laser module (Class 2)",
}


def _base(name):
    head, _, tail = name.rpartition("_")
    return head if head and tail.isdigit() else name


def prototype_positions(m):
    """Give every solid of the prototype its part number (the shopping-list line) and a position
    number (1, 2, 3 ... for each copy). Returns [{pn, pos, tag, item, base, label, centre, size}]
    and renames the solids to their tag, e.g. 'P11-2 x_motor'."""
    with open(os.path.join(ROOT, "docs", "prototype_bom.csv")) as fh:
        bom = {r["item"]: r for r in csv.DictReader(fh)}
    counts, out, items = {}, [], []
    for group, name, label, shape, colour in m.items:
        base = _base(name)
        row = bom[PROTO_PARTS[base]]
        pn = row["part_no"]
        counts[pn] = counts.get(pn, 0) + 1
        tag = f"{pn}-{counts[pn]}"
        bb = (shape.val() if hasattr(shape, "val") else shape).BoundingBox()
        c = bb.center
        side = "front (operator side)" if c.y < -60 else "back" if c.y > 60 else "middle"
        end = "infeed end" if c.x < 250 else "outfeed end" if c.x > 950 else "middle"
        out.append({"pn": pn, "pos": counts[pn], "tag": tag, "item": row["item"], "base": base, "label": label,
                    "where": f"{side}, {end}, {round(c.z)} mm up",
                    "centre": [round(bb.center.x, 1), round(bb.center.y, 1), round(bb.center.z, 1)],
                    "size": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)]})
        items.append((group, f"{tag} {base}", label, shape, colour))
    m.items = items
    return out


def export_prototype():
    m = build_prototype()
    os.makedirs(CAD_DIR, exist_ok=True)
    positions = prototype_positions(m)
    path = os.path.join(CAD_DIR, "prototype_1to10.step")
    old_step = os.path.join(CAD_DIR, "prototype_1to5.step")
    if os.path.exists(old_step):
        os.remove(old_step)
    m.assembly().export(path)                       # every solid is named 'P11-2 x_motor' in the CAD tree
    # the 3D assembly in the app (Prototype tab): the same solids, in metres, and where each one is
    os.makedirs(WEB_MODELS, exist_ok=True)
    exportGLTF(m.assembly(scale=0.001), os.path.join(WEB_MODELS, "prototype.glb"), binary=True,
               tolerance=0.0004, angularTolerance=0.3)
    import json
    with open(os.path.join(WEB_MODELS, "prototype_positions.json"), "w") as fh:
        json.dump(positions, fh, indent=0)
    # cut list: every extrusion, grouped by profile, length and use
    counts = {}
    for c in m.cuts:
        counts[c] = counts.get(c, 0) + 1
    cut = os.path.join(CAD_DIR, "prototype_cut_list.csv")
    with open(cut, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["profile", "length_mm", "use", "quantity"])
        for (profile, length, use), n in sorted(counts.items()):
            w.writerow([profile, length, use, n])
    # every position: which part, which copy, what it is, where it sits (mm)
    with open(os.path.join(CAD_DIR, "prototype_positions.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["position", "part_no", "copy", "part (shopping list)", "what it is", "where", "x_mm", "y_mm", "z_mm"])
        for p in positions:
            w.writerow([p["tag"], p["pn"], p["pos"], p["item"], p["label"], p["where"], *p["centre"]])
    old = os.path.join(CAD_DIR, "prototype_parts.csv")
    if os.path.exists(old):
        os.remove(old)
    return [path, cut, os.path.join(WEB_MODELS, "prototype.glb")]


# ======================================================================= command line
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    need_cadquery()
    what = argv[0] if argv else "all"
    written = []
    if what in ("all", "parts"):
        files = argv[1:] if what == "parts" and len(argv) > 1 else sorted(glob.glob(os.path.join(ROOT, "examples", "nc1", "*.nc1")))
        written += export_parts(files)
    if what in ("all", "cell"):
        written += export_cell()
    if what in ("all", "prototype"):
        written += export_prototype()
    for p in written:
        print(f"{os.path.relpath(p, ROOT):45s} {os.path.getsize(p) / 1024:8.0f} kB")


if __name__ == "__main__":
    main()
