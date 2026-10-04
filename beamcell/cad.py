"""
Real CAD for the cell, the parts and the 1:5 prototype - solid models you can open in Fusion 360,
SolidWorks, FreeCAD, Onshape or Inventor (STEP), and the same model for the 3D view (GLB).

    python3 -m beamcell.cad                    everything below
    python3 -m beamcell.cad cell               cad/beam_cell.step  + web/models/*.glb (the 3D view)
    python3 -m beamcell.cad parts [files.nc1]  cad/parts/<mark>.step - one solid per NC1 part, with its
                                               holes, slots, notches and end cuts (default: examples/nc1)
    python3 -m beamcell.cad prototype          cad/prototype_1to5.step + cad/prototype_cut_list.csv

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
    rail_z = M.RAIL_Z * mm
    run_z = rail_z - 550                                    # underside of the runway beams
    by, bz = M.BEAM_Y * mm, M.BED_Z * mm

    # building steelwork: runway beams on columns, crane rails
    for side, y in (("front", -W / 2), ("back", W / 2)):
        m.section(f"runway_{side}", "Runway beam UB 457x191x67 - carries a bridge rail", STRUCTURE,
                  "UB 457x191x67", L, at=(x0, y, run_z))
        m.box(f"crane_rail_{side}", "Crane rail 60x50 flat bar - both bridges' wheels run on it", STEEL,
              x0, x0 + L, y - 30, y + 30, run_z + 453.4, run_z + 503.4)
        for i in range(5):
            x = (xa + i * (xb - xa) / 4) * mm
            m.section(f"column_{side}", "Column UC 254x254x73 holding up the runway", STRUCTURE,
                      "UC 254x254x73", run_z, at=(x - 127, y, 0), axis="z")
            m.box(f"base_plate_{side}", "Column base plate 500x500x25, anchored to the floor", DARK,
                  x - 250, x + 250, y - 250, y + 250, 0, 25)

    # roller bed
    rr = M.ROLLER_R * mm
    bx0, bx1 = -300, M.WORK_LENGTH * mm + 300
    for dy in (-400, 400):
        m.box("bed_rail", "Bed side rail RHS 120x80 - holds the roller bearings", BED,
              bx0, bx1, by + dy - 40, by + dy + 40, bz - rr - 160, bz - rr - 40)
        for x in np.arange(bx0 + 100, bx1, 2000):
            m.box("bed_leg", "Bed leg SHS 80x80", BED, x - 40, x + 40, by + dy - 40, by + dy + 40, 0, bz - rr - 160)
    for x in M.ROLLER_X:
        X = x * mm
        m.cyl("bed_roller", "Bed roller 100 mm dia - the bar rests on these (top = bed height 900 mm)", ALU,
              (X, by - 360, bz - rr), (X, by + 360, bz - rr), rr)
        for dy in (-400, 400):
            m.box("roller_bearing", "Roller bearing block", DARK, X - 50, X + 50, by + dy - 40, by + dy + 40,
                  bz - rr - 70, bz - rr + 30)
    # scrap tray under the bed
    tz = M.SCRAP_TRAY_Z * mm
    m.box("scrap_tray_floor", "Scrap tray - offcuts fall between the rollers into it", BLUE_TRAY,
          bx0, bx1, by - 300, by + 300, tz - 40, tz)
    for dy in (-300, 300):
        m.box("scrap_tray_side", "Scrap tray side", BLUE_TRAY, bx0, bx1, by + dy - 15, by + dy + 15, tz - 40, tz + 200)
    # outfeed table
    ox0, ox1, oy0, oy1 = (v * mm for v in M.OUTFEED_DECK)
    m.box("outfeed_deck", "Outfeed table - steel grating deck at bed height; finished parts are put down here",
          GREEN, ox0, ox1, oy0, oy1, bz - 30, bz)
    for y in (oy0 + 40, oy1 - 40):
        m.box("outfeed_frame", "Outfeed table frame", BED, ox0, ox1, y - 40, y + 40, bz - 130, bz - 30)
        for x in np.arange(ox0 + 100, ox1, 2000):
            m.box("outfeed_leg", "Outfeed table leg", BED, x - 40, x + 40, y - 40, y + 40, 0, bz - 130)

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
    m.box("stack_pole", "Stack light pole", DARK, gx + 3330, gx + 3370, -fy - 1020, -fy - 980, 900, 2100)
    for i, (lamp, colour) in enumerate((("red", (1, 0.16, 0.12)), ("amber", (1, 0.69, 0)), ("green", (0.13, 0.83, 0.42)), ("blue", (0.18, 0.48, 1)))):
        z = 2600 - i * 120
        m.cyl(f"lamp_{lamp}", f"Stack light - {lamp}", colour, (gx + 3350, -fy - 1000, z - 55), (gx + 3350, -fy - 1000, z + 55), 60)

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
        for dx in (-320, 320):
            m.cyl("wheel", "Crane wheel 180 dia", RUBBER, (dx, y - 40, -20), (dx, y + 40, -20), 90, group=g)
        ys = -180 if y > 0 else 180
        m.cyl("drive_motor", f"{hand.name} long-travel motor + gearbox (X axis)", DARK, (300, y + ys, 120), (520, y + ys, 120), 80, group=g)
    # carriage on the bridge (Y axis), with its motor
    g = f"{key}.carriage"
    m.box("carriage", f"{hand.name} carriage - runs across the bridge (Y axis)", DARK, -310, 310, -250, 250, -180, 180, group=g)
    m.box("carriage_band", f"{hand.name} carriage", paint, -315, 315, -255, 255, -180, -120, group=g)
    m.cyl("carriage_motor", f"{hand.name} cross-travel motor (Y axis)", RUBBER, (0, 0, 180), (0, 0, 480), 85, group=g)
    m.cyl("mast_motor", f"{hand.name} lift motor (Z axis)", RUBBER, (200, 150, 180), (200, 150, 420), 70, group=g)
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
    else:
        m.cyl("magnet_stem", "Magnet stem with load cell", DARK, (0, 0, 0), (0, 0, T - 30), 30, group=grp)
        m.cyl("magnet_pad", "Lifting magnet (battery-backed, BS EN 13155) - 500 kg", RED, (0, 0, T - 30), (0, 0, T), 110, group=grp)


def export_cell():
    """cad/beam_cell.step (everything, posed at park) and the 3D view's GLB files."""
    m = build_cell()
    os.makedirs(CAD_DIR, exist_ok=True)
    os.makedirs(WEB_MODELS, exist_ok=True)
    # GLB for the 3D view (metres): the static cell, and one file with every moving body in its own frame
    exportGLTF(m.assembly(scale=0.001), os.path.join(WEB_MODELS, "cell.glb"), binary=True, tolerance=0.002, angularTolerance=0.35)
    moving = sorted({it[0] for it in m.items if it[0]})
    exportGLTF(m.assembly(scale=0.001, groups=moving), os.path.join(WEB_MODELS, "moving.glb"), binary=True,
               tolerance=0.001, angularTolerance=0.3)
    import json
    with open(os.path.join(WEB_MODELS, "labels.json"), "w") as fh:
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
    path = os.path.join(CAD_DIR, "beam_cell.step")
    step.export(path)
    return [path, os.path.join(WEB_MODELS, "cell.glb"), os.path.join(WEB_MODELS, "moving.glb")]


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


# ======================================================================= the 1:5 working prototype
PROTO_SCALE = 0.2               # 1:5
PROTO_LENGTH = 1200.0           # mm of work area (= 6 m at full size)


def build_prototype():
    """A 1:5 desktop prototype made from parts you can buy (see docs/PROTOTYPE.md): 20x40 / 20x60
    aluminium T-slot frame, NEMA 17 motors on GT2 belts and T8 lead screws, two SO-101-size
    servo arms, a pen / laser-pointer 'torch' and a small electromagnet. Labels say what to buy."""
    need_cadquery()
    s = PROTO_SCALE
    m = Model("beam_cell_prototype_1to5")
    Lx = PROTO_LENGTH + 300                                  # rails run past the work area for parking
    x0 = -150.0
    W = M.WIDTH * 1000 * s                                   # 600 between rail centres
    rail_z = M.RAIL_Z * 1000 * s                             # 680
    bz = M.BED_Z * 1000 * s                                  # 180
    by = M.BEAM_Y * 1000 * s                                 # -100
    E = "20x40 V-slot aluminium extrusion"
    # base frame on the table, uprights, top rails
    for y in (-W / 2, W / 2):
        m.extrusion("base_rail", f"{E} - base rail {Lx:.0f} mm", ALU, (20, 40), (x0, y, 20), (x0 + Lx, y, 20))
        m.extrusion("top_rail", f"{E} - gantry rail {Lx:.0f} mm (the bridges' wheels run on it)", ALU, (20, 40),
                    (x0, y, rail_z - 20), (x0 + Lx, y, rail_z - 20))
        for x in (x0 + 10, x0 + Lx / 2, x0 + Lx - 10):
            m.extrusion("upright", f"{E} - upright {rail_z - 80:.0f} mm", ALU, (20, 40), (x, y, 40), (x, y, rail_z - 40))
    for x in (x0 + 10, x0 + Lx - 10):
        for z in (20, rail_z - 20):
            m.extrusion("cross_member", f"{E} - cross member {W - 20:.0f} mm", ALU, (20, 40), (x, -W / 2 + 10, z), (x, W / 2 - 10, z))
    # roller bed: two 20x20 rails, 20 mm rollers on 8 mm shafts every 200 mm (= 1 m full size)
    for dy in (-60, 60):
        m.extrusion("bed_rail", "20x20 V-slot - bed rail 1300 mm", ALU, (20, 20), (-50, by + dy, bz - 30), (PROTO_LENGTH + 50, by + dy, bz - 30))
    for x in (100 + 200 * i for i in range(6)):
        m.cyl("bed_roller", "Bed roller: 20 mm aluminium tube on an 8 mm shaft, 2 x 608 bearings", ALU,
              (x, by - 50, bz - 10), (x, by + 50, bz - 10), 10)
        for dy in (-60, 60):
            m.box("bed_bracket", "3D-printed roller bracket (cad/prototype: print in PETG)", PRINTED,
                  x - 12, x + 12, by + dy - 10, by + dy + 10, bz - 40, bz - 5)
    for x in (-40, PROTO_LENGTH / 2, PROTO_LENGTH + 40):
        for dy in (-60, 60):
            m.extrusion("bed_leg", "20x20 V-slot - bed leg", ALU, (20, 20), (x, by + dy, 40), (x, by + dy, bz - 40))
    m.box("scrap_tray", "Scrap tray: 3D-printed or folded aluminium sheet", BLUE_TRAY, -50, PROTO_LENGTH + 50, by - 45, by + 45, 40, 50)
    m.box("outfeed_table", "Outfeed table: 6 mm plywood / MDF strip on 20x20 legs", GREEN,
          -50, PROTO_LENGTH + 50, M.OUTFEED_DECK[2] * 1000 * s, M.OUTFEED_DECK[3] * 1000 * s, bz - 6, bz)
    # model beam on the bed: a 3D-printed UB 305x165 at 1:5 (61 x 33 mm)
    ub = S.get("UB 305x165x40")
    tiny = dict(ub, h=ub["h"] * s, b=ub["b"] * s, tw=max(ub["tw"] * s, 1.6), tf=max(ub["tf"] * s, 2.0), r=ub["r"] * s)
    m.add("model_beam", "Model beam: UB 305x165x40 at 1:5, 3D printed (see docs/SCALE_MODEL.md)", section_solid(tiny, 1000).translate((20, by, bz)), STEEL)
    # each hand: bridge (20x60 on V-wheel plates), carriage plate, Z axis (20x20 + T8 screw), arm, tool
    for hand, hx in ((M.make_hands()[1], 150.0), (M.make_hands()[0], 900.0)):
        name = hand.name
        paint = tuple(int(hand.color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        top = rail_z + 20
        m.extrusion("bridge", f"{name} bridge: 20x60 V-slot {W + 60:.0f} mm", ALU, (60, 20), (hx, -W / 2 - 30, top + 10), (hx, W / 2 + 30, top + 10), use="bridge")
        for y in (-W / 2, W / 2):
            m.box("gantry_plate", f"{name} bridge end: V-slot gantry plate with 4 V-wheels", DARK, hx - 45, hx + 45, y - 25, y + 25, top - 5, top)
            for dx in (-30, 30):
                m.cyl("v_wheel", "V-wheel (Delrin, 625 bearings)", RUBBER, (hx + dx, y - 12, top - 15), (hx + dx, y + 12, top - 15), 12)
        m.box("x_motor", f"{name} X motor: NEMA 17 (42x42x48) driving both sides through an 8 mm cross shaft and GT2 belts",
              RUBBER, hx + 20, hx + 62, -W / 2 + 40, -W / 2 + 88, top + 20, top + 62)
        m.cyl("cross_shaft", "8 mm cross shaft with GT2 20T pulleys at both ends", STEEL, (hx + 41, -W / 2, top + 41), (hx + 41, W / 2, top + 41), 4)
        cy = 0.0
        m.box("carriage_plate", f"{name} carriage: V-slot gantry plate on the bridge (Y axis)", DARK, hx - 45, hx + 45, cy - 45, cy + 45, top - 15, top - 10)
        # Y motor hangs under the carriage plate beside the Z axis; its GT2 belt runs along the bridge
        m.box("y_motor", f"{name} Y motor: NEMA 17 + GT2 belt along the bridge", RUBBER, hx + 15, hx + 57, cy - 21, cy + 21, top - 63, top - 15)
        z_len = 300.0
        beam_top = bz + tiny["h"]
        tool = 300 if hand.tool == "torch" else 255          # arm base to tool tip in this pose
        zb = beam_top + (10 if hand.tool == "torch" else 0) + tool   # pen 10 mm above the steel, magnet on it
        m.extrusion("z_axis", f"{name} Z axis: 20x20 V-slot {z_len:.0f} mm on a T8 lead screw (slides through the carriage)", ALU,
                    (20, 20), (hx, cy, zb), (hx, cy, zb + z_len), use="Z axis")
        # Z motor stands on the carriage plate; its T8 lead screw drives a nut fixed to the Z axis
        m.box("z_motor", f"{name} Z motor: NEMA 17 with integrated T8 x 2 mm lead screw", RUBBER, hx - 80, hx - 38, cy - 21, cy + 21, top - 10, top + 38)
        m.box("z_motor_mount", f"{name} Z motor bracket (3D printed)", PRINTED, hx - 82, hx - 15, cy - 25, cy + 25, top - 15, top - 10)
        m.cyl("lead_screw", "T8 x 2 mm lead screw, 300 mm", STEEL, (hx - 59, cy, top - 10), (hx - 59, cy, zb), 4)
        m.box("lead_nut", f"{name} lead-screw nut block on the Z axis (3D printed + brass T8 nut)", PRINTED, hx - 70, hx - 10, cy - 12, cy + 12, zb, zb + 15)
        m.box("arm_mount", f"{name} arm mount plate (3D printed)", PRINTED, hx - 30, hx + 30, cy - 30, cy + 30, zb - 6, zb)
        # SO-101-size servo arm hanging under the Z axis (envelope: base, upper arm, forearm, wrist)
        m.cyl("arm_base", f"{name} arm: SO-101 type 6-servo arm kit (STS3215 servos) - base", paint, (hx, cy, zb - 6), (hx, cy, zb - 56), 32)
        m.box("arm_upper", f"{name} arm: upper arm (~110 mm)", paint, hx - 15, hx + 15, cy - 15, cy + 15, zb - 166, zb - 56)
        m.box("arm_fore", f"{name} arm: forearm (~135 mm)", paint, hx - 12, hx + 123, cy - 12, cy + 12, zb - 190, zb - 166)
        m.box("arm_wrist", f"{name} arm: wrist", paint, hx + 110, hx + 140, cy - 14, cy + 14, zb - 230, zb - 190)
        if hand.tool == "torch":
            m.cyl("pen_tool", "Cutter 'torch' for the prototype: pen or 5 mW laser pointer in a 3D-printed holder (marks the cut lines)",
                  RUBBER, (hx + 125, cy, zb - 230), (hx + 125, cy, zb - 300), 7)
        else:
            m.cyl("magnet_tool", "Handler magnet: 12 V 25 mm lifting electromagnet (holds 2.5 kg)", RED,
                  (hx + 125, cy, zb - 230), (hx + 125, cy, zb - 255), 12.5)
    # electronics and safety on the frame
    m.box("control_box", "Control box: Jetson Orin Nano, FluidNC 6-axis board, 24 V and 12 V supplies, fuses, safety relay",
          DARK, x0 + Lx + 30, x0 + Lx + 230, -150, 150, 0, 160)
    m.box("estop", "Emergency stop: 22 mm red mushroom, 2 NC contacts, yellow box (BS EN ISO 13850)", YELLOW,
          x0 + Lx + 60, x0 + Lx + 130, -W / 2 - 80, -W / 2 - 10, 0, 70)
    m.cyl("estop_head", "Emergency stop head", RED, (x0 + Lx + 95, -W / 2 - 45, 70), (x0 + Lx + 95, -W / 2 - 45, 95), 20)
    m.box("enclosure_front", "Enclosure door: 3 mm polycarbonate on 20x20 frame, with a safety interlock switch", (0.8, 0.85, 0.9),
          x0 + 200, x0 + 900, -W / 2 - 52, -W / 2 - 49, 40, rail_z - 40)
    m.box("door_switch", "Door interlock switch (magnetic coded, NC) - opens = protective stop", RED,
          x0 + 880, x0 + 900, -W / 2 - 70, -W / 2 - 52, 300, 340)
    m.box("camera", "Camera: USB wide-angle (or IMX219 CSI) on a 20x20 post - YOLO watches the cell", RUBBER,
          x0 - 60, x0 - 20, -W / 2 - 20, -W / 2 + 20, rail_z + 60, rail_z + 100)
    m.extrusion("camera_post", "20x20 V-slot camera post", ALU, (20, 20), (x0 - 40, -W / 2, 20), (x0 - 40, -W / 2, rail_z + 60))
    return m


# which shopping-list line (docs/prototype_bom.csv) each solid in the prototype is
PROTO_PARTS = {
    "base_rail": "V-slot 20x40 aluminium extrusion", "top_rail": "V-slot 20x40 aluminium extrusion",
    "upright": "V-slot 20x40 aluminium extrusion", "cross_member": "V-slot 20x40 aluminium extrusion",
    "bed_rail": "V-slot 20x20 aluminium extrusion", "bed_leg": "V-slot 20x20 aluminium extrusion",
    "z_axis": "V-slot 20x20 aluminium extrusion", "camera_post": "V-slot 20x20 aluminium extrusion",
    "bridge": "V-slot 20x60 aluminium extrusion",
    "bed_roller": "Bed rollers", "bed_bracket": "Roller brackets", "outfeed_table": "Outfeed table board",
    "scrap_tray": "Scrap tray", "model_beam": "Model beams",
    "gantry_plate": "V-wheel gantry plate kits", "carriage_plate": "V-wheel gantry plate kits",
    "v_wheel": "V-wheel gantry plate kits",
    "x_motor": "NEMA 17 stepper motor", "y_motor": "NEMA 17 stepper motor",
    "z_motor": "NEMA 17 with integrated T8 lead screw", "lead_screw": "NEMA 17 with integrated T8 lead screw",
    "z_motor_mount": "Z motor bracket (3D printed)", "lead_nut": "Lead-screw nut block (3D printed)",
    "cross_shaft": "8 mm cross shafts + pillow blocks",
    "arm_mount": "Arm mount plate (3D printed)",
    "arm_base": "SO-101 6-servo arm kit (follower)", "arm_upper": "SO-101 6-servo arm kit (follower)",
    "arm_fore": "SO-101 6-servo arm kit (follower)", "arm_wrist": "SO-101 6-servo arm kit (follower)",
    "pen_tool": "Cutter 'torch' for the prototype", "magnet_tool": "Handler magnet",
    "control_box": "Control box", "estop": "Emergency stop station", "estop_head": "Emergency stop station",
    "enclosure_front": "Polycarbonate sheet 3 mm", "door_switch": "Door interlock switch",
    "camera": "USB wide-angle camera (safety zone)",
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
    path = os.path.join(CAD_DIR, "prototype_1to5.step")
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
