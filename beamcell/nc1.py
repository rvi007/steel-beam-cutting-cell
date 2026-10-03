"""
DSTV NC1 files - the format Tekla Structures, Advance Steel and SDS2 export for beam CNC
machines (one file per part, plain text).

Blocks read:
    ST  header: piece mark, steel grade, quantity, profile, length, section sizes, end-cut angles
    BO  holes (round and slotted)                      -> Part.holes
    AK  outer contour of a face (end cuts, copes...)   -> Part.outlines
    IK  inner contour (an opening inside a face)       -> Part.inner
    SI, KO, PU, KA, ...  marking / bending - noted in the report, not cut
    EN  end of file

Faces: v = front (web / upright leg), o = top flange, u = bottom flange (flat leg of an angle),
h = behind (back of the web). Coordinates in mm: x along the part, y across the face
(see sections.face_to_section for how y is measured on each face).
"""
import math
import re

from beamcell import sections as S
from beamcell import uk_codes as UK
from beamcell.parts import Part

NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
FACES = "vouh"
KIND_FROM_CODE = {"I": "I", "U": "U", "C": "U", "L": "L", "M": "M", "RO": "RO", "RU": "RO"}


def _blocks(text):
    """[(code, [data lines])] - comment lines (**) dropped."""
    blocks = []
    for raw in text.replace("\r", "").split("\n"):
        if raw.strip().startswith("**") or not raw.strip():
            continue
        if re.match(r"^[A-Z][A-Z0-9]\s*$", raw):          # a block code alone at the start of a line
            blocks.append((raw.strip(), []))
        elif blocks:
            blocks[-1][1].append(raw)
    return blocks


def _num(s, default=0.0):
    m = NUM.search(s or "")
    return float(m.group()) if m else default


def _face_and_numbers(line, last_face):
    t = line.strip()
    face = last_face
    if t and t[0] in FACES:
        face, t = t[0], t[1:]
    return face, [float(x) for x in NUM.findall(t)]


def _arc_points(p0, p1, r, steps=6):
    """Points between p0 and p1 on an arc of radius |r| (DSTV: radius given on the first point)."""
    (x0, y0), (x1, y1) = p0, p1
    chord = math.hypot(x1 - x0, y1 - y0)
    R = abs(r)
    if R < 1e-9 or chord < 1e-9 or chord > 2 * R:
        return []
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    h = math.sqrt(max(R * R - chord * chord / 4, 0))
    nx, ny = -(y1 - y0) / chord, (x1 - x0) / chord
    sign = 1 if r > 0 else -1
    cx, cy = mx - sign * nx * h, my - sign * ny * h
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    return [(cx + R * math.cos(a0 + da * i / steps), cy + R * math.sin(a0 + da * i / steps)) for i in range(1, steps)]


def _contours(lines):
    """Contour lines of one AK/IK block -> {face: [points]} (arcs expanded)."""
    out = {}
    face = "v"
    raw = {}
    for ln in lines:
        face, nums = _face_and_numbers(ln, face)
        if len(nums) >= 2:
            raw.setdefault(face, []).append((nums[0], nums[1], nums[2] if len(nums) > 2 else 0.0))
    for f, pts in raw.items():
        poly = []
        for i, (x, y, r) in enumerate(pts):
            poly.append((x, y))
            if r and i + 1 < len(pts):
                poly += _arc_points((x, y), pts[i + 1][:2], r)
        if len(poly) > 1 and math.hypot(poly[0][0] - poly[-1][0], poly[0][1] - poly[-1][1]) < 1e-6:
            poly.pop()
        if _area(poly) < 0:
            poly.reverse()
        out[f] = poly
    return out


def _area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def read(text, filename="part.nc1"):
    """Parse one NC1 file. Returns (Part, report) - report is a list of plain-English notes."""
    report = []
    blocks = _blocks(text)
    st = next((lines for code, lines in blocks if code == "ST"), None)
    if st is None:
        raise ValueError("not an NC1 file: no ST (start) block")
    f = [ln.strip() for ln in st] + [""] * 24
    mark = f[3] or f[1] or filename.rsplit(".", 1)[0]
    grade = f[4] or UK.DEFAULT_GRADE
    qty = int(_num(f[5], 1)) or 1
    profile, code = f[6], f[7].upper()
    length = _num(f[8].split(",")[0])
    h, b, tf, tw, r, mass = (_num(f[i]) for i in (9, 10, 11, 12, 13, 14))
    kind = KIND_FROM_CODE.get(code, "?")
    sec = S.find(profile, kind if kind != "?" else None)
    custom = None
    if sec is None:
        if kind in ("I", "U", "L") and h > 0 and b > 0:
            custom = S.custom(kind, h, b, tw, tf, r, mass, name=f"{profile} (from file)")
            report.append(f"Profile '{profile}' is not in the UK library - using the sizes in the file.")
            title = custom["title"]
        else:
            raise ValueError(f"profile '{profile}' (type {code}) is not supported")
    else:
        title = sec["title"]
        diffs = [(n, a, sec[k]) for n, a, k in (("depth", h, "h"), ("width", b, "b"), ("web", tw, "tw"),
                                                 ("flange", tf, "tf")) if a and abs(a - sec[k]) > 0.6]
        if diffs:
            report.append("Header sizes differ from the UK table: " +
                          ", ".join(f"{n} {a:g} vs {v:g}" for n, a, v in diffs))
    report.append(f"{mark}: {title}, {length:.0f} mm, {grade}, qty {qty}")

    holes, outlines, inner = [], {}, []
    other = {}
    for code_, lines in blocks:
        if code_ == "BO":
            face = "v"
            for ln in lines:
                face, nums = _face_and_numbers(ln, face)
                if len(nums) < 3:
                    continue
                x, y, d = nums[0], nums[1], nums[2]
                hole = {"face": face, "x": x, "y": y, "d": d}
                if len(nums) >= 5 and nums[4] > 0:             # slotted: depth, slot length, width, angle
                    hole["slot"] = d + nums[4]
                    hole["angle"] = nums[6] if len(nums) >= 7 else 0.0
                holes.append(hole)
        elif code_ == "AK":
            outlines.update(_contours(lines))
        elif code_ == "IK":
            for face, pts in _contours(lines).items():
                inner.append({"face": face, "points": [list(p) for p in pts]})
        elif code_ not in ("ST", "EN"):
            other[code_] = other.get(code_, 0) + 1
    by_face = {}
    for hole in holes:
        by_face[hole["face"]] = by_face.get(hole["face"], 0) + 1
    if holes:
        report.append("Holes: " + ", ".join(f"{n} on face {k}" for k, n in sorted(by_face.items())))
    if outlines:
        report.append("Outer contours on faces: " + ", ".join(sorted(outlines)))
    if inner:
        report.append(f"Inner cut-outs: {len(inner)}")
    names = {"SI": "hard stamping", "KO": "marking lines", "PU": "powder marking", "KA": "bending",
             "SC": "saw cuts", "TO": "tolerances", "UE": "camber", "PR": "profile"}
    for k, n in other.items():
        report.append(f"Ignored {n} {names.get(k, k)} block(s) - not done by a plasma cell")
    mitres = {}
    for key, idx in (("start", 16), ("end", 17)):
        web = _num(f[idx])
        fl = _num(f[idx + 2])
        if (web or fl) and not outlines:
            mitres[key] = {"web": web, "flange": fl}
    part = Part(mark, title, length, qty, grade, holes, outlines, inner, mitres=mitres,
                source=f"nc1:{filename}", custom=custom)
    return part, report


def write(part):
    """A Part as NC1 text (so manual parts can go to a real machine, and for the examples)."""
    s = part.sec
    code = {"I": "I", "U": "U", "L": "L"}[s["kind"]]
    profile = s["title"].replace(" ", "").replace("x", "*")
    lines = ["ST", "** written by beamcell", "  ORDER", "  DRAWING", "  1", f"  {part.mark}", f"  {part.grade}",
             f"  {part.qty}", f"  {profile}", f"  {code}", f"  {part.length:10.2f}",
             f"  {s['h']:10.2f}", f"  {s['b']:10.2f}", f"  {s['tf']:10.2f}", f"  {s['tw']:10.2f}",
             f"  {s.get('r', 0):10.2f}", f"  {s.get('m', 0):10.3f}", "  0.000"]
    m = part.mitres or {}
    lines += [f"  {(m.get('start') or {}).get('web', 0):10.3f}", f"  {(m.get('end') or {}).get('web', 0):10.3f}",
              f"  {(m.get('start') or {}).get('flange', 0):10.3f}", f"  {(m.get('end') or {}).get('flange', 0):10.3f}",
              "  ", "  ", "  ", "  "]
    if part.holes:
        lines.append("BO")
        for hole in part.holes:
            line = f"  {hole['face']} {hole['x']:10.2f}s {hole['y']:10.2f} {hole['d']:8.2f} {0:8.2f}"
            if hole.get("slot"):
                line += f" {hole['slot'] - hole['d']:8.2f} {0:8.2f} {hole.get('angle', 0):8.2f}"
            lines.append(line)
    for face in part.faces():
        pts = part.face_outline(face)
        lines.append("AK")
        for x, y in pts + [pts[0]]:
            lines.append(f"  {face} {x:10.2f} {y:10.2f} {0:8.2f}")
    for item in part.inner:
        lines.append("IK")
        pts = item["points"]
        for x, y in pts + [pts[0]]:
            lines.append(f"  {item['face']} {x:10.2f} {y:10.2f} {0:8.2f}")
    lines.append("EN")
    return "\n".join(lines) + "\n"
