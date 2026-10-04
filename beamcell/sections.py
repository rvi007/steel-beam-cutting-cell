"""
UK steel sections: the library, name lookup, and the exact cross-section shape.

Families (see data/uk_sections.json for the standards and the data source):
    UB, UC, UBP          I sections            BS 4-1
    PFC                  parallel flange channel BS 4-1
    EA, UA               equal / unequal angles BS EN 10056-1
    SHS/RHS/CHS -HF/-CF  hollow sections       BS EN 10210-2 (hot) / 10219-2 (cold)

Section coordinates (mm), looking along the bar:
    u = across (left to right = machine -Y to +Y), v = up, origin at the bottom middle.

How each type lies on the machine bed:
    I  (UB/UC/UBP)  web upright, centred.
    PFC             web upright on the +Y side (the Cutter's side), flanges pointing to -Y.
    Angles          one leg upright on the +Y side (the longer leg), the other flat on the bed.
    Hollow          shown and exported only - this cell cuts open sections.

Every open section is a set of PLATES (flanges, web, legs). Each plate has the DSTV face
letter used in NC1 files: v = web / upright leg (front), o = top flange, u = bottom flange /
flat leg.
"""
import json
import math
import os
import re

DATA = os.path.join(os.path.dirname(__file__), "data", "uk_sections.json")
FAMILY_NAMES = {
    "UB": "Universal beam", "UC": "Universal column", "UBP": "Universal bearing pile",
    "PFC": "Parallel flange channel", "EA": "Equal angle", "UA": "Unequal angle",
    "SHS-HF": "Square hollow (hot finished)", "RHS-HF": "Rectangular hollow (hot finished)",
    "CHS-HF": "Circular hollow (hot finished)", "SHS-CF": "Square hollow (cold formed)",
    "RHS-CF": "Rectangular hollow (cold formed)", "CHS-CF": "Circular hollow (cold formed)",
}
KIND = {"UB": "I", "UC": "I", "UBP": "I", "PFC": "U", "EA": "L", "UA": "L",
        "SHS-HF": "M", "RHS-HF": "M", "SHS-CF": "M", "RHS-CF": "M", "CHS-HF": "RO", "CHS-CF": "RO"}
CUTTABLE = {"I", "U", "L"}
ARC_STEPS = 6          # straight pieces per quarter circle in the outline

_library = None


def library():
    """{family: [section dict, ...]} - each section has 'family', 'name', 'title' and its sizes."""
    global _library
    if _library is None:
        with open(DATA) as fh:
            raw = json.load(fh)
        _library = {}
        for fam, rows in raw["families"].items():
            out = []
            for r in rows:
                s = dict(r)
                s["family"] = fam
                s["kind"] = KIND[fam]
                s["title"] = f"{fam.split('-')[0]} {r['name']}" + (" (CF)" if fam.endswith("-CF") else "")
                _complete(s)
                out.append(s)
            _library[fam] = out
    return _library


def _complete(s):
    """Fill in the sizes every type needs (thicknesses, radii) so the rest of the code is simple."""
    k = s["kind"]
    if k == "L":
        s["tw"] = s["tf"] = s["t"]
        s["r"] = s["r1"]
    elif k == "M":
        t = s["t"]
        if s["family"].endswith("-HF"):           # BS EN 10210-2: outside corner 1.5t, inside 1.0t
            s["ro"], s["ri"] = 1.5 * t, 1.0 * t
        else:                                     # BS EN 10219-2: outside 2t / 2.5t / 3t
            s["ro"] = 2.0 * t if t <= 6 else 2.5 * t if t <= 10 else 3.0 * t
            s["ri"] = s["ro"] - t
        s["tw"] = s["tf"] = t
    elif k == "RO":
        s["h"] = s["b"] = s["d"]
        s["tw"] = s["tf"] = s["t"]


def get(title):
    """Section by its title, e.g. 'UB 457x191x67' or 'SHS 100x100x5.0 (CF)'."""
    for rows in library().values():
        for s in rows:
            if s["title"] == title:
                return s
    raise KeyError(f"unknown section {title!r}")


def find(text, kind=None):
    """Best match for a profile name as other software writes it, e.g. 'UB457*191*67',
    'UKB457x191x67', '457x191x67UB', 'PFC200*90*30', 'L100*100*10'. None if no match."""
    t = text.upper().replace("*", "X").replace(" ", "")
    nums = re.findall(r"\d+(?:\.\d+)?", t)
    if len(nums) < 2:
        return None
    letters = re.sub(r"[\d.X]", "", t)
    fam_hint = None
    for code, fam in (("UKB", "UB"), ("UKC", "UC"), ("UKBP", "UBP"), ("UBP", "UBP"), ("UB", "UB"),
                      ("UC", "UC"), ("PFC", "PFC"), ("UKPFC", "PFC"), ("SHS", "SHS"), ("RHS", "RHS"),
                      ("CHS", "CHS"), ("UKA", "L"), ("L", "L"), ("RSA", "L")):
        if code in letters:
            fam_hint = fam
            break
    want = [float(n) for n in nums]
    best = None
    for fam, rows in library().items():
        if kind and KIND[fam] != kind:
            continue
        if fam_hint and not (fam == fam_hint or fam.startswith(fam_hint) or
                             (fam_hint == "L" and KIND[fam] == "L")):
            continue
        for s in rows:
            have = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s["name"])]
            if len(have) == len(want) and all(abs(a - b) < 0.6 for a, b in zip(have, want)):
                score = 0 if not fam.endswith("-CF") else 1      # prefer hot finished
                if best is None or score < best[0]:
                    best = (score, s)
    return best[1] if best else None


def custom(kind, h, b, tw, tf, r=0.0, mass=0.0, name="custom"):
    """A section that isn't in the library (e.g. from an NC1 file header)."""
    s = {"family": "CUSTOM", "kind": kind, "name": name, "title": name, "h": h, "b": b,
         "tw": tw, "tf": tf, "r": r, "m": mass}
    if kind == "L":
        s["t"] = tw
        s["r1"], s["r2"] = r, r / 2
    return s


# ------------------------------------------------------------------ geometry
def _arc(cx, cy, r, a0, a1, steps=ARC_STEPS):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / steps), cy + r * math.sin(a0 + (a1 - a0) * i / steps))
            for i in range(steps + 1)]


def _round_rect(w, h, r, cy):
    """Rounded rectangle centred at (0, cy), anticlockwise."""
    r = min(r, w / 2, h / 2)
    x, y = w / 2 - r, h / 2 - r
    pts = []
    for cx_, cy_, a in ((x, -y, -math.pi / 2), (x, y, 0), (-x, y, math.pi / 2), (-x, -y, math.pi)):
        pts += _arc(cx_, cy + cy_, r, a, a + math.pi / 2)
    return pts


def outline(s):
    """The real cross-section: (outer polygon, [hole polygons]) in mm, anticlockwise outer.
    Includes root radii (and toe radii for angles, corner radii for hollow sections)."""
    k = s["kind"]
    h, b = s["h"], s["b"]
    if k == "I":
        tw, tf, r = s["tw"], s["tf"], s["r"]
        w = tw / 2
        pts = [(-b / 2, 0), (b / 2, 0), (b / 2, tf)]
        pts += _arc(w + r, tf + r, r, -math.pi / 2, -math.pi)                 # bottom right root
        pts += _arc(w + r, h - tf - r, r, math.pi, math.pi / 2)               # top right root
        pts += [(b / 2, h - tf), (b / 2, h), (-b / 2, h), (-b / 2, h - tf)]
        pts += _arc(-w - r, h - tf - r, r, math.pi / 2, 0)                    # top left root
        pts += _arc(-w - r, tf + r, r, 0, -math.pi / 2)                       # bottom left root
        pts += [(-b / 2, tf)]
        return pts, []
    if k == "U":
        tw, tf, r = s["tw"], s["tf"], s["r"]
        x = b / 2 - tw                                                         # inside face of the web
        pts = [(-b / 2, 0), (b / 2, 0), (b / 2, h), (-b / 2, h), (-b / 2, h - tf)]
        pts += _arc(x - r, h - tf - r, r, math.pi / 2, 0)
        pts += _arc(x - r, tf + r, r, 0, -math.pi / 2)
        pts += [(-b / 2, tf)]
        return pts, []
    if k == "L":
        t, r1, r2 = s["t"], s["r1"], s["r2"]
        x = b / 2 - t                                                          # inside face of upright leg
        pts = [(-b / 2, 0), (b / 2, 0), (b / 2, h)]
        pts += _arc(x + r2, h - r2, r2, math.pi / 2, math.pi)                 # toe of upright leg
        pts += _arc(x - r1, t + r1, r1, 0, -math.pi / 2)                      # root
        pts += _arc(-b / 2 + r2, t - r2, r2, math.pi / 2, math.pi)            # toe of flat leg
        return _clean(pts), []
    if k == "M":
        t = s["t"]
        return _round_rect(b, h, s["ro"], h / 2), [_round_rect(b - 2 * t, h - 2 * t, s["ri"], h / 2)[::-1]]
    if k == "RO":
        d, t = s["d"], s["t"]
        n = ARC_STEPS * 6
        outer = [(d / 2 * math.cos(2 * math.pi * i / n), d / 2 + d / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]
        inner = [((d / 2 - t) * math.cos(-2 * math.pi * i / n), d / 2 + (d / 2 - t) * math.sin(-2 * math.pi * i / n))
                 for i in range(n)]
        return outer, [inner]
    raise ValueError(k)


def _clean(pts):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-6:
        out.pop()
    return out


def plates(s):
    """The flat plates of an open section, as dicts:
        face      DSTV face letter (v, o, u)
        u0,u1,v0,v1   the plate's rectangle in section coordinates (mm)
        across    'v' if the plate is horizontal (a flange: thickness is vertical), 'u' if upright
        span      the face's DSTV y range: (start, direction) - see face_to_section()
    """
    k = s["kind"]
    h, b, tw, tf = s["h"], s["b"], s["tw"], s["tf"]
    if k == "I":
        return [dict(face="o", u0=-b / 2, u1=b / 2, v0=h - tf, v1=h, flat=True),
                dict(face="v", u0=-tw / 2, u1=tw / 2, v0=tf, v1=h - tf, flat=False),
                dict(face="u", u0=-b / 2, u1=b / 2, v0=0, v1=tf, flat=True)]
    if k == "U":
        return [dict(face="o", u0=-b / 2, u1=b / 2, v0=h - tf, v1=h, flat=True),
                dict(face="v", u0=b / 2 - tw, u1=b / 2, v0=tf, v1=h - tf, flat=False),
                dict(face="u", u0=-b / 2, u1=b / 2, v0=0, v1=tf, flat=True)]
    if k == "L":
        t = s["t"]
        return [dict(face="v", u0=b / 2 - t, u1=b / 2, v0=t, v1=h, flat=False),
                dict(face="u", u0=-b / 2, u1=b / 2, v0=0, v1=t, flat=True)]
    return []


def face_to_section(s, face, y):
    """DSTV face coordinate y (mm) -> section coordinate across that face.
    For flat plates it returns u, for upright plates v.

    Conventions used (DSTV, as Tekla writes them):
        v (web / upright leg): y measured up from the underside of the section.
        o, u (flanges):        y measured from the front edge (the +Y side, where the
                               web of a channel and the heel of an angle are).
        u (flat leg of angle): y measured from the heel (+Y side).
    """
    if face in ("v", "h"):
        return y
    return s["b"] / 2 - y


def section_to_face(s, face, c):
    """Inverse of face_to_section."""
    if face in ("v", "h"):
        return c
    return s["b"] / 2 - c


def face_width(s, face):
    """Size of a face across (its DSTV y range is 0..this)."""
    return s["h"] if face in ("v", "h") else s["b"]


def summary(s):
    """Small dict for the web app."""
    keys = ("family", "name", "title", "kind", "h", "b", "tw", "tf", "t", "r", "r1", "r2", "d", "ro", "ri",
            "m", "C", "N", "n", "add")
    out = {k: s[k] for k in keys if k in s}
    out["cuttable"] = s["kind"] in CUTTABLE
    return out
