"""
IFC export of the cell's fabricated structural steelwork - for a steel detailer working in Tekla Structures.

    python3 -m beamcell.ifc_export      cad/beam_cell_steel_12m.ifc  + cad/beam_cell_steel_12m.csv (cut list)
                                        cad/beam_cell_steel_20m.ifc  + cad/beam_cell_steel_20m.csv

What is in it: the runway beams and crane rails, the columns with their base and cap plates, longitudinal
X-bracing in one end bay a side, the roller bed frame, the outfeed table frame, the bar end stop post and
the energy-chain tray brackets. Every member is a real UK section in S355, with a mark, an assembly and its
length, at the same place as in the 3D model (beamcell/cad.py build_cell). Nothing moving, no guarding,
no bought-in parts. See docs/TEKLA.md.

The file is IFC2X3 (Coordination View 2.0 style): the safest version for Tekla's import and for
"Convert IFC objects" to native Tekla parts. Units millimetres. Axes as everywhere in the project:
origin at the bar datum (the end stop), X along the bed (infeed -> outfeed end), Y across
(+Y = the back runway), Z up from the finished floor.

This file reads beamcell/machine.py and beamcell/sections.py; it does not import cad.py (that needs CadQuery).
"""
import csv
import math
import os
import sys
import time
import uuid

from beamcell import machine as M
from beamcell import sections as S

try:
    import ifcopenshell
    import ifcopenshell.guid
except ImportError:                                   # only needed to write the .ifc - the member list works without it
    ifcopenshell = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAD_DIR = os.path.join(ROOT, "cad")
GRADE = "S355"
STEEL_DENSITY = 7850e-9                     # kg per mm^3

# the same numbers as beamcell/cad.py (kept in step by hand - cad.py needs CadQuery to import)
RUNWAY = "UB 457x191x67"
COLUMN = "UC 254x254x73"
RUNWAY_STOCK_MAX = 18000                    # longest UB we ask a stockholder for; longer runways get a splice at a column
HOLLOW_STOCK_MAX = 12000                    # hollow sections: 12 m stock lengths
BASE_PLATE = (500, 500, 25)                 # PL25 500x500, 4 holes for M24 holding-down bolts
CAP_PLATE = (300, 300, 20)                  # PL20 300x300 on top of each column, the runway sits on it
RAIL = (60, 50)                             # crane rail: 60 wide x 50 high flat bar on top of the runway


def runway_z():
    """Underside of the runway beams (mm) - as RUNWAY_Z in cad.py."""
    return M.RAIL_Z * 1000 - 550


# ---------------------------------------------------------------------------------------------
# Tekla's UK catalogue names
# ---------------------------------------------------------------------------------------------

def _num(v):
    """250.0 -> '250', 6.3 -> '6.3'."""
    return f"{v:g}"


def tekla_name(title):
    """'UB 457x191x67' -> 'UB457*191*67', 'RHS 120x80x5.0' -> 'RHS120*80*5', 'EA 70x70x7.0' -> 'L70*70*7'."""
    family, size = title.split(" ")[0], title.split(" ")[1]
    parts = "*".join(_num(float(p)) for p in size.split("x"))
    if family == "EA":
        family = "L"                        # Tekla's UK catalogue lists equal angles as L
    return family + parts


def hollow_mass(s):
    """kg/m of a hollow section from its real shape (the library gives it too; this is a cross-check)."""
    t, h, b, ro, ri = s["t"], s["h"], s["b"], s["ro"], s["ri"]
    area = h * b - (h - 2 * t) * (b - 2 * t) - (4 - math.pi) * (ro ** 2 - ri ** 2)
    return area * STEEL_DENSITY * 1e3


# ---------------------------------------------------------------------------------------------
# The member list
# ---------------------------------------------------------------------------------------------

def _length(a, b):
    return math.dist(a, b)


def _r(p):
    return tuple(round(float(v)) for v in p)


def _bar(out, mark, assembly, kind, title, start, end, ref, note=""):
    """A member cut from a rolled or hollow section. start/end: the centre line of the section (mm).
    ref: the direction of the section's local x axis (across the flanges / the 'b' side)."""
    s = S.get(title)
    start, end = _r(start), _r(end)
    length = round(_length(start, end))
    out.append({"mark": mark, "assembly": assembly, "kind": kind, "profile": tekla_name(title),
                "section": dict(s), "plate": None, "start": start, "end": end, "rotation": tuple(ref),
                "grade": GRADE, "length_mm": length, "mass_kg": round(s["m"] * length / 1000, 1), "note": note})


def _plate(out, mark, assembly, width, depth, thick, centre, note="", kind="plate", axis=(1, 0, 0), name=None):
    """A plate or flat: 'width' x 'thick' in section, 'depth' long. centre = centre of its underside (flat
    plates, extruded up by 'thick') - or for a flat bar laid along 'axis', the start of its centre line."""
    if kind == "plate":                     # lying flat: extruded up through its thickness
        start = _r(centre)
        end = _r((centre[0], centre[1], centre[2] + thick))
        length = round(depth)
        profile = name or f"PL{_num(thick)}*{_num(width)}"
        dims = {"width": width, "depth": depth, "thickness": thick}
        ref = (1, 0, 0)
    else:                                   # a flat bar along 'axis' (the crane rail): section width x thick
        start = _r(centre)
        end = _r(tuple(c + a * depth for c, a in zip(centre, axis)))
        length = round(depth)
        profile = name or f"FL{_num(width)}*{_num(thick)}"
        dims = {"width": width, "depth": thick, "thickness": thick}
        ref = (0, 1, 0) if abs(axis[1]) < 0.5 else (1, 0, 0)       # the width lies flat, across the bar
    mass = round(width * depth * thick * STEEL_DENSITY, 1)
    out.append({"mark": mark, "assembly": assembly, "kind": kind if kind == "plate" else "member", "profile": profile,
                "section": None, "plate": dims, "start": start, "end": end, "rotation": ref,
                "grade": GRADE, "length_mm": length, "mass_kg": mass, "note": note})


def _split(x0, x1, n):
    """Cut x0..x1 into n equal pieces."""
    step = (x1 - x0) / n
    return [(x0 + i * step, x0 + (i + 1) * step) for i in range(n)]


def column_xs():
    """Column lines along X (mm): a column at least every 4 m, from one end of the rails to the other."""
    xa, xb = M.X_LIMITS
    bays = math.ceil((xb - xa) / 4.0)
    return [(xa + i * (xb - xa) / bays) * 1000 for i in range(bays + 1)]


def members(length_m=None):
    """Every member of the steel frame for a 12 m or 20 m machine, as a list of dicts:
        mark, assembly, kind (beam / column / plate / member), profile (Tekla UK name), section (dict, or None),
        plate (width / depth / thickness for plates and flats, or None), start / end (mm, the extrusion line),
        rotation (direction of the profile's local x axis), grade, length_mm, mass_kg, note.
    length_m: set the machine size first (and put it back afterwards); None = the size set now."""
    if length_m is not None:
        before = M.WORK_LENGTH
        M.set_length(length_m)
        try:
            return members(None)
        finally:
            M.set_length(before)

    out = []
    xa, xb = M.X_LIMITS
    W = M.WIDTH * 1000
    rz = runway_z()
    ub, uc = S.get(RUNWAY), S.get(COLUMN)
    x0, x1 = (xa - 0.3) * 1000, (xb + 0.3) * 1000             # the runway runs 300 mm past the end columns
    cols = column_xs()
    n = {"C": 0, "BP": 0, "CP": 0, "RB": 0, "R": 0, "BX": 0, "TB": 0}

    def mark(p):
        n[p] = n.get(p, 0) + 1
        return f"{p}{n[p]}"

    for side, y in (("FRONT", -W / 2), ("BACK", W / 2)):
        # runway: one length, or spliced over the column nearest the middle when it is too long for stock
        pieces = [(x0, x1)]
        if x1 - x0 > RUNWAY_STOCK_MAX:
            xs = min(cols[1:-1], key=lambda c: abs(c - (x0 + x1) / 2))
            pieces = [(x0, xs), (xs, x1)]
        zc = rz + ub["h"] / 2
        for a, b in pieces:
            note = "" if len(pieces) == 1 else "spliced over a column (bolted cover-plate splice to be designed)"
            _bar(out, mark("RB"), f"RUNWAY-{side}", "beam", RUNWAY, (a, y, zc), (b, y, zc), (0, 1, 0), note)
        # crane rail flat on top, split where the runway is
        top = rz + ub["h"]
        for a, b in pieces:
            _plate(out, mark("R"), f"RUNWAY-{side}", RAIL[0], b - a, RAIL[1], (a, y, top + RAIL[1] / 2),
                   note="crane rail, continuously welded or clipped to the runway top flange", kind="flat")
        # columns, each with its base plate and its cap plate
        for x in cols:
            cz0, cz1 = BASE_PLATE[2], rz - CAP_PLATE[2]
            # web along X (as in cad.py): the section's 'b' (local x) runs across, along Y
            _bar(out, mark("C"), f"COLUMNS-{side}", "column", COLUMN, (x, y, cz0), (x, y, cz1), (0, 1, 0))
            _plate(out, mark("BP"), f"COLUMNS-{side}", BASE_PLATE[0], BASE_PLATE[1], BASE_PLATE[2], (x, y, 0),
                   note="4 holes 26 dia for M24 holding-down bolts at 380 x 380 centres; grout 25-40 mm under")
            _plate(out, mark("CP"), f"COLUMNS-{side}", CAP_PLATE[0], CAP_PLATE[1], CAP_PLATE[2], (x, y, cz1),
                   note="cap plate, runway bottom flange bolted to it (4 M20)")
        # X-bracing in the first bay, in the plane of the columns (outside the machine's moving envelope)
        xL, xR = cols[0] + uc["h"] / 2, cols[1] - uc["h"] / 2
        zlo, zhi = 300.0, rz - 200.0
        # the two diagonals pass each other either side of a 10 mm centre gusset where they cross
        for (ax, az), (bx, bz), dy in (((xL, zlo), (xR, zhi), -40), ((xL, zhi), (xR, zlo), 40)):
            _bar(out, mark("BX"), f"BRACING-{side}", "member", "EA 70x70x7.0", (ax, y + dy, az), (bx, y + dy, bz), (0, 1, 0),
                 note="X-bracing, gusset plates to the column flanges by the detailer")
        # energy-chain tray brackets under the runway (as cad.py): flat 60 wide x 30 deep, outboard of the runway
        y_tray = (W / 2 + 350) * (1 if y > 0 else -1)
        ylo, yhi = min(y, y_tray) - 90, max(y, y_tray) + 90
        for xb_ in _arange(x0 + 500, (xa + xb) / 2 * 1000 + 400, 2000):
            _plate(out, mark("TB"), f"TRAY-{side}", 60, yhi - ylo, 30, (xb_, ylo, M.RAIL_Z * 1000 - 125),
                   note="energy-chain tray bracket, bolted to the runway", kind="flat", axis=(0, 1, 0))

    # roller bed: two side rails RHS 120x80 (top 40 mm under the rollers' axle line), legs SHS 80x80 every 2 m
    by, bz = M.BEAM_Y * 1000, M.BED_Z * 1000
    rr = M.ROLLER_R * 1000
    bx0, bx1 = -300.0, M.WORK_LENGTH * 1000 + 300
    rail_bot = bz - rr - 160
    for dy in (-400, 400):
        pieces = _split(bx0, bx1, math.ceil((bx1 - bx0) / HOLLOW_STOCK_MAX))
        for a, b in pieces:
            _bar(out, mark("BR"), "BED", "beam", "RHS 120x80x5.0", (a, by + dy, rail_bot + 60), (b, by + dy, rail_bot + 60),
                 (0, 1, 0), note="" if len(pieces) == 1 else "joined over a leg (welded, full penetration, or a bolted sleeve)")
        for x in _arange(bx0 + 100, bx1, 2000):
            _bar(out, mark("BL"), "BED", "column", "SHS 80x80x5.0", (x, by + dy, 0), (x, by + dy, rail_bot), (1, 0, 0),
                 note="150x150x10 foot plate with 2 M12 anchors (fixings by others)")

    # outfeed table: two frame rails RHS 100x80 (100 high), legs SHS 80x80 every 2 m; the grating deck is bought in
    ox0, ox1, oy0, oy1 = (v * 1000 for v in M.OUTFEED_DECK)
    for y in (oy0 + 40, oy1 - 40):
        pieces = _split(ox0, ox1, math.ceil((ox1 - ox0) / HOLLOW_STOCK_MAX))
        for a, b in pieces:
            _bar(out, mark("OF"), "OUTFEED", "beam", "RHS 100x80x5.0 (CF)", (a, y, bz - 80), (b, y, bz - 80), (0, 1, 0),
                 note="carries the 30 mm grating deck (bought in)")
        for x in _arange(ox0 + 100, ox1, 2000):
            _bar(out, mark("OL"), "OUTFEED", "column", "SHS 80x80x5.0", (x, y, 0), (x, y, bz - 130), (1, 0, 0))

    # bar end stop: a post on a base plate, up to just under bed height (the datum block above it is machined, bought in)
    ex, ey = -435.0, by
    _plate(out, mark("ESP"), "END-STOP", 300, 300, 20, (ex, ey, 0), note="4 holes 18 dia for M16 anchors")
    _bar(out, mark("ES"), "END-STOP", "column", "SHS 100x100x6.3", (ex, ey, 20), (ex, ey, bz - 20), (1, 0, 0),
         note="the datum block and laser bracket bolt to its top (machined parts, not in this model)")
    return out


def _arange(a, b, step):
    out, x = [], a
    while x < b - 1e-6:
        out.append(x)
        x += step
    return out


# ---------------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------------

def envelope():
    """The box the bridges, carriages and arms move in (mm): no steel may enter it."""
    xa, xb = M.X_LIMITS
    W = M.WIDTH
    return ((xa - 0.5) * 1000, (xb + 0.5) * 1000, (-W / 2 + 0.25) * 1000, (W / 2 - 0.25) * 1000,
            M.BED_Z * 1000, (M.RAIL_Z + 0.7) * 1000)


def bbox(m):
    """Axis-aligned box round a member (mm), from its centre line and its section."""
    (sx, sy, sz), (ex, ey, ez) = m["start"], m["end"]
    d = [e - s for s, e in zip(m["start"], m["end"])]
    L = math.sqrt(sum(v * v for v in d)) or 1
    d = [v / L for v in d]
    ref = m["rotation"]
    up = (d[1] * ref[2] - d[2] * ref[1], d[2] * ref[0] - d[0] * ref[2], d[0] * ref[1] - d[1] * ref[0])
    if m["section"]:
        hx, hy = m["section"]["b"] / 2, m["section"]["h"] / 2
    elif m["kind"] == "plate":
        hx, hy = m["plate"]["width"] / 2, m["plate"]["depth"] / 2
    else:
        hx, hy = m["plate"]["width"] / 2, m["plate"]["thickness"] / 2
    lo, hi = [], []
    for i in range(3):
        ext = abs(ref[i]) * hx + abs(up[i]) * hy
        lo.append(min(m["start"][i], m["end"][i]) - ext)
        hi.append(max(m["start"][i], m["end"][i]) + ext)
    return tuple(lo), tuple(hi)


def in_envelope(m):
    ex0, ex1, ey0, ey1, ez0, ez1 = envelope()
    lo, hi = bbox(m)
    return lo[0] < ex1 and hi[0] > ex0 and lo[1] < ey1 and hi[1] > ey0 and lo[2] < ez1 and hi[2] > ez0


# ---------------------------------------------------------------------------------------------
# The IFC file
# ---------------------------------------------------------------------------------------------

class _Ifc:
    """A small IFC2X3 writer: just the entities Tekla needs."""

    def __init__(self, name):
        f = self.f = ifcopenshell.file(schema="IFC2X3")
        self.name = name
        person = f.createIfcPerson(None, None, "Beam Cell", None, None, None, None, None)
        org = f.createIfcOrganization(None, "Beam Cell", None, None, None)
        app = f.createIfcApplication(org, "1.0", "Beam Cell IFC export", "beamcell.ifc_export")
        self.owner = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(person, org, None), app,
                                             None, "ADDED", None, None, None, int(time.time()))
        units = f.createIfcUnitAssignment([
            f.createIfcSIUnit(None, "LENGTHUNIT", "MILLI", "METRE"),
            f.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
            f.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE"),
            f.createIfcSIUnit(None, "MASSUNIT", "KILO", "GRAM"),
            f.createIfcSIUnit(None, "PLANEANGLEUNIT", None, "RADIAN"),
        ])
        self.origin = self.axis3((0, 0, 0))
        self.ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1e-5, self.origin, f.createIfcDirection((0.0, 1.0)))
        self.body = f.createIfcGeometricRepresentationSubContext("Body", "Model", None, None, None, None,
                                                                 self.ctx, None, "MODEL_VIEW", None)
        self.project = f.createIfcProject(self.guid(), self.owner, name, "Beam Cell structural steelwork", None, None, None,
                                          [self.ctx], units)
        site_pl = f.createIfcLocalPlacement(None, self.axis3((0, 0, 0)))
        self.site = f.createIfcSite(self.guid(), self.owner, "Site", None, None, site_pl, None, None, "ELEMENT",
                                    None, None, None, None, None)
        bld_pl = f.createIfcLocalPlacement(site_pl, self.axis3((0, 0, 0)))
        self.building = f.createIfcBuilding(self.guid(), self.owner, "Beam Cell", None, None, bld_pl, None, None,
                                            "ELEMENT", None, None, None)
        self.storey_pl = f.createIfcLocalPlacement(bld_pl, self.axis3((0, 0, 0)))
        self.storey = f.createIfcBuildingStorey(self.guid(), self.owner, "Ground floor", "Finished floor level = Z 0",
                                                None, self.storey_pl, None, None, "ELEMENT", 0.0)
        f.createIfcRelAggregates(self.guid(), self.owner, None, None, self.project, [self.site])
        f.createIfcRelAggregates(self.guid(), self.owner, None, None, self.site, [self.building])
        f.createIfcRelAggregates(self.guid(), self.owner, None, None, self.building, [self.storey])
        self.material = f.createIfcMaterial(GRADE)
        self.contained = []
        self.with_material = []
        self.profiles = {}

    def guid(self):
        return ifcopenshell.guid.compress(uuid.uuid4().hex)

    def axis3(self, p, z=None, x=None):
        f = self.f
        loc = f.createIfcCartesianPoint(tuple(float(v) for v in p))
        if z is None:
            return f.createIfcAxis2Placement3D(loc, None, None)
        return f.createIfcAxis2Placement3D(loc, f.createIfcDirection(tuple(float(v) for v in z)),
                                           f.createIfcDirection(tuple(float(v) for v in x)))

    def profile(self, m):
        """The cross-section, made once per profile name."""
        if m["profile"] in self.profiles:
            return self.profiles[m["profile"]]
        f, s = self.f, m["section"]
        pos = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)
        if s and s["kind"] == "I":
            p = f.createIfcIShapeProfileDef("AREA", m["profile"], pos, s["b"], s["h"], s["tw"], s["tf"], s["r"])
        elif s and s["kind"] == "M":
            p = f.createIfcRectangleHollowProfileDef("AREA", m["profile"], pos, s["b"], s["h"], s["t"], s["ri"], s["ro"])
        elif s and s["kind"] == "L":
            p = f.createIfcLShapeProfileDef("AREA", m["profile"], pos, s["h"], s["b"], s["t"], s["r1"], s["r2"],
                                            None, None, None)
        elif m["kind"] == "plate":
            p = f.createIfcRectangleProfileDef("AREA", m["profile"], pos, m["plate"]["width"], m["plate"]["depth"])
        else:
            p = f.createIfcRectangleProfileDef("AREA", m["profile"], pos, m["plate"]["width"], m["plate"]["thickness"])
        self.profiles[m["profile"]] = p
        return p

    def add(self, m):
        f = self.f
        d = [e - s for s, e in zip(m["start"], m["end"])]
        L = math.sqrt(sum(v * v for v in d))
        axis = [v / L for v in d]
        solid = f.createIfcExtrudedAreaSolid(self.profile(m), self.axis3((0, 0, 0)), f.createIfcDirection((0.0, 0.0, 1.0)), float(L))
        shape = f.createIfcProductDefinitionShape(None, None, [f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", [solid])])
        place = f.createIfcLocalPlacement(self.storey_pl, self.axis3(m["start"], axis, m["rotation"]))
        cls = {"beam": "IfcBeam", "column": "IfcColumn", "plate": "IfcPlate", "member": "IfcMember"}[m["kind"]]
        el = f.create_entity(cls, GlobalId=self.guid(), OwnerHistory=self.owner, Name=m["mark"],
                             Description=m["profile"], ObjectType=m["profile"], ObjectPlacement=place,
                             Representation=shape, Tag=m["mark"])
        props = [("Mark", f.createIfcLabel(m["mark"])), ("Assembly", f.createIfcLabel(m["assembly"])),
                 ("Profile", f.createIfcLabel(m["profile"])), ("Grade", f.createIfcLabel(m["grade"])),
                 ("Length", f.createIfcLengthMeasure(float(m["length_mm"]))),
                 ("Weight", f.createIfcMassMeasure(float(m["mass_kg"])))]
        if m["note"]:
            props.append(("Notes", f.createIfcText(m["note"])))
        pset = f.createIfcPropertySet(self.guid(), self.owner, "Pset_BeamCellSteel", None,
                                      [f.createIfcPropertySingleValue(k, None, v, None) for k, v in props])
        f.createIfcRelDefinesByProperties(self.guid(), self.owner, None, None, [el], pset)
        self.with_material.append(el)
        return el

    def assembly(self, name, parts):
        f = self.f
        pl = f.createIfcLocalPlacement(self.storey_pl, self.axis3((0, 0, 0)))
        a = f.createIfcElementAssembly(self.guid(), self.owner, name, None, "ASSEMBLY", pl, None, name, "FACTORY", "NOTDEFINED")
        f.createIfcRelAggregates(self.guid(), self.owner, None, None, a, parts)
        pset = f.createIfcPropertySet(self.guid(), self.owner, "Pset_BeamCellSteel", None,
                                      [f.createIfcPropertySingleValue("Assembly", None, f.createIfcLabel(name), None)])
        f.createIfcRelDefinesByProperties(self.guid(), self.owner, None, None, [a], pset)
        self.contained.append(a)

    def write(self, path):
        f = self.f
        f.createIfcRelContainedInSpatialStructure(self.guid(), self.owner, None, None, self.contained, self.storey)
        f.createIfcRelAssociatesMaterial(self.guid(), self.owner, None, None, self.with_material, self.material)
        f.write(path)


def export_ifc(length_m, path):
    """Write the steel frame of a 12 m or 20 m machine to an IFC2X3 file. Returns the member list."""
    if ifcopenshell is None:
        raise RuntimeError("needs ifcopenshell (pip install ifcopenshell)")
    ms = members(length_m)
    ifc = _Ifc(f"Beam Cell {length_m:g} m - structural steelwork")
    groups = {}
    for m in ms:
        groups.setdefault(m["assembly"], []).append(ifc.add(m))
    for name, parts in groups.items():
        ifc.assembly(name, parts)
    ifc.write(path)
    return ms


def write_cut_list(ms, path):
    """Cut list: one line per mark, then totals per profile, then the grand total."""
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["mark", "assembly", "profile", "grade", "qty", "length_mm", "unit_kg", "total_kg", "note"])
        for m in ms:
            w.writerow([m["mark"], m["assembly"], m["profile"], m["grade"], 1, m["length_mm"], m["mass_kg"], m["mass_kg"], m["note"]])
        w.writerow([])
        w.writerow(["TOTALS BY PROFILE", "", "profile", "grade", "qty", "total_length_mm", "", "total_kg", ""])
        by = {}
        for m in ms:
            t = by.setdefault(m["profile"], [0, 0, 0.0])
            t[0] += 1
            t[1] += m["length_mm"]
            t[2] += m["mass_kg"]
        for p, (q, L, kg) in sorted(by.items()):
            w.writerow(["", "", p, GRADE, q, L, "", round(kg, 1), ""])
        w.writerow([])
        w.writerow(["TOTAL", "", "", GRADE, len(ms), "", "", round(sum(m["mass_kg"] for m in ms), 1),
                    "excludes bolts, welds, gussets and connection plates (add about 5-10 %)"])


def main(argv=None):
    os.makedirs(CAD_DIR, exist_ok=True)
    try:
        for length in M.LENGTHS:
            base = os.path.join(CAD_DIR, f"beam_cell_steel_{length:g}m")
            ms = export_ifc(length, base + ".ifc")
            write_cut_list(ms, base + ".csv")
            print(f"{length:g} m: {len(ms)} members, {sum(m['mass_kg'] for m in ms) / 1000:.2f} t -> {base}.ifc, .csv")
    finally:
        M.set_length(12.0)            # the 12 m machine is the default everywhere else
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
