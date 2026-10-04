"""
Parts, the checks they must pass, and nesting parts onto a stock bar.

A Part is described the same way an NC1 (DSTV) file describes it - all sizes in mm:
    section   e.g. "UB 457x191x67"
    length    along the bar
    holes     [{face, x, y, d, slot (length, 0 = round), angle}]  - DSTV face coordinates
    outlines  {face: [(x, y), ...]}  the final shape of each face (copes, mitres, end cuts).
              Faces without one are plain rectangles, possibly changed by `copes` / `mitres`.
    inner     [{face, points}]  inside cut-outs (DSTV IK)
    copes     [{end: start|end, side: top|bottom, length, depth, radius}]  - manual notches
    mitres    {start: {web, flange}, end: {web, flange}}  - manual end-cut angles in degrees

DSTV face coordinates: x along the part from its start, y across the face (see sections.py).
"""
import math

from beamcell import sections as S
from beamcell import uk_codes as UK

TOL = 0.01


class Part:
    def __init__(self, mark, section, length, qty=1, grade=UK.DEFAULT_GRADE, holes=None,
                 outlines=None, inner=None, copes=None, mitres=None, source="manual", custom=None):
        self.mark = str(mark)
        self.section_title = section
        self.custom = custom                 # section dict when it isn't in the UK library
        self.length = float(length)
        self.qty = int(qty)
        self.grade = grade
        self.holes = list(holes or [])
        self.outlines = dict(outlines or {})
        self.inner = list(inner or [])
        self.copes = list(copes or [])
        self.mitres = dict(mitres or {})
        self.source = source

    # ---------------------------------------------------------------- data
    def to_dict(self):
        return {"mark": self.mark, "section": self.section_title, "length": self.length, "qty": self.qty,
                "grade": self.grade, "holes": self.holes,
                "outlines": {f: [list(p) for p in pts] for f, pts in self.outlines.items()},
                "inner": self.inner, "copes": self.copes, "mitres": self.mitres, "source": self.source,
                "custom": self.custom}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("mark", "P"), d["section"], d["length"], d.get("qty", 1), d.get("grade", UK.DEFAULT_GRADE),
                   d.get("holes"), {f: [tuple(p) for p in pts] for f, pts in (d.get("outlines") or {}).items()},
                   d.get("inner"), d.get("copes"), d.get("mitres"), d.get("source", "manual"), d.get("custom"))

    @property
    def sec(self):
        return self.custom if self.custom else S.get(self.section_title)

    @property
    def weight(self):
        return self.sec.get("m", 0) * self.length / 1000

    def faces(self):
        return [p["face"] for p in S.plates(self.sec)]

    # ---------------------------------------------------------------- shape of each face
    def face_outline(self, face):
        """Final outline of a face, anticlockwise, in DSTV face coordinates."""
        if face in self.outlines and len(self.outlines[face]) >= 3:
            return [tuple(p) for p in self.outlines[face]]
        left = self._end_profile(face, "start")          # from y = W down to y = 0
        right = self._end_profile(face, "end")[::-1]     # from y = 0 up to y = W
        return _dedupe(right + left)

    def _end_profile(self, face, end):
        """One end of a face as a polyline from the top (y = W) to the bottom (y = 0)."""
        s = self.sec
        W = S.face_width(s, face)
        L = self.length
        flip = (lambda x: x) if end == "start" else (lambda x: L - x)
        m = (self.mitres or {}).get(end, {}) or {}
        web = math.tan(math.radians(m.get("web", 0.0) or 0.0))
        flange = math.tan(math.radians(m.get("flange", 0.0) or 0.0))
        h = s["h"]
        if face in ("v", "h"):
            def base(y):
                return web * (h - y) if web >= 0 else -web * y
        else:
            v_mid = h - s["tf"] / 2 if face == "o" else s["tf"] / 2
            shift = web * (h - v_mid) if web >= 0 else -web * v_mid

            def base(y):
                return shift + (flange * y if flange >= 0 else -flange * (W - y))
        top = [c for c in self.copes if c["end"] == end and c["side"] == "top"]
        bottom = [c for c in self.copes if c["end"] == end and c["side"] == "bottom"]
        if face in ("v", "h") and s["kind"] in ("I", "U"):
            pts = [(base(W), W)]
            if top:
                c = top[0]
                N, n, R = c["length"], c["depth"], max(c.get("radius", UK.DEFAULT_COPE_RADIUS), 0.0)
                pts = [(N, W), (N, W - n + R)] + _arc(N - R, W - n + R, R, 0, -90) + [(N - R, W - n), (base(W - n), W - n)]
            if bottom:
                c = bottom[0]
                N, n, R = c["length"], c["depth"], max(c.get("radius", UK.DEFAULT_COPE_RADIUS), 0.0)
                pts += [(base(n), n), (N - R, n)] + _arc(N - R, n - R, R, 90, 0) + [(N, n - R), (N, 0)]
            else:
                pts.append((base(0), 0))
        else:
            removed = (face == "o" and top) or (face == "u" and bottom)
            if removed and s["kind"] in ("I", "U"):
                N = (top or bottom)[0]["length"]
                pts = [(max(N, base(W)), W), (max(N, base(0)), 0)]
            else:
                pts = [(base(W), W), (base(0), 0)]
        return [(flip(x), y) for x, y in pts]

    def chains(self, face):
        """Cut paths on a face: the parts of its outline that aren't the plate's own long edges.
        Returns [{"points": [(x, y)...], "end": "start"|"end"|"mid"}]."""
        pts = self.face_outline(face)
        W = S.face_width(self.sec, face)
        n = len(pts)
        on_edge = [abs(pts[i][1] - pts[(i + 1) % n][1]) < TOL and
                   (abs(pts[i][1]) < TOL or abs(pts[i][1] - W) < TOL) for i in range(n)]
        if not any(on_edge):
            return [{"points": pts + [pts[0]], "end": "mid"}]
        start = next(i for i in range(n) if on_edge[i])
        out, cur = [], None
        for k in range(1, n + 1):
            i = (start + k) % n
            if on_edge[i]:
                if cur:
                    out.append(cur)
                cur = None
            else:
                if cur is None:
                    cur = [pts[i]]
                cur.append(pts[(i + 1) % n])
        if cur:
            out.append(cur)
        return [{"points": c, "end": "start" if sum(p[0] for p in c) / len(c) < self.length / 2 else "end"}
                for c in out]

    def end_is_square(self, end):
        """True if this end is a plain square cut on every face (so it can share a cut)."""
        x_end = 0.0 if end == "start" else self.length
        for face in self.faces():
            ch = [c for c in self.chains(face) if c["end"] == end]
            if len(ch) != 1 or any(abs(p[0] - x_end) > 0.5 for p in ch[0]["points"]):
                return False
        return True

    # ---------------------------------------------------------------- checks
    def check(self):
        """List of issues: {level: error|warning, item, text, ref}."""
        out = []
        s = self.sec

        def add(level, item, text, ref=""):
            out.append({"level": level, "item": item, "text": text, "ref": ref})

        if s["kind"] not in S.CUTTABLE:
            add("error", "section", "hollow sections need a rotating chuck - this cell cuts I, channel "
                "and angle sections", "MACHINE")
            return out
        if self.length < UK.MIN_PART_LENGTH:
            add("error", "length", f"shorter than {UK.MIN_PART_LENGTH:.0f} mm", "MACHINE")
        faces = self.faces()
        for i, hole in enumerate(self.holes):
            out += [dict(x, item=f"hole {i + 1}") for x in self._check_hole(hole, faces)]
        for a in range(len(self.holes)):
            for b in range(a + 1, len(self.holes)):
                h1, h2 = self.holes[a], self.holes[b]
                if self.norm_face(h1["face"]) != self.norm_face(h2["face"]):
                    continue
                d0 = max(h1["d"], h2["d"])
                gap = math.hypot(h1["x"] - h2["x"], h1["y"] - h2["y"])
                p1 = UK.min_distances(d0)["p1"]
                if gap < p1 - 1e-6:
                    add("error", f"holes {a + 1} & {b + 1}", f"{gap:.0f} mm apart, minimum {p1:.0f}",
                        "BS EN 1993-1-8 Table 3.3 (p1 >= 2.2 d0)")
        for i, c in enumerate(self.copes):
            item = f"notch {i + 1} ({c['side']}, {c['end']})"
            if s["kind"] not in ("I", "U"):
                add("error", item, "notches are for I and channel sections")
                continue
            R = c.get("radius", UK.DEFAULT_COPE_RADIUS)
            if c["depth"] < s["tf"] + s["r"] - 1e-6:
                add("error", item, f"depth {c['depth']:.0f} mm must clear the flange and root "
                    f"(at least tf + r = {s['tf'] + s['r']:.0f} mm)", "UK detailing (Blue Book n)")
            if R < UK.MIN_CORNER_RADIUS:
                add("error", item, f"corner radius below {UK.MIN_CORNER_RADIUS:.0f} mm",
                    "BS EN 1090-2 (re-entrant corners)")
            if c["length"] <= R or c["depth"] <= R:
                add("error", item, "notch must be bigger than its corner radius")
            if c["length"] > self.length / 2:
                add("error", item, "notch longer than half the part")
            advice = UK.cope_advice(s, c["depth"], c["length"])
            if advice:
                add("warning", item, advice, "SCI P358")
        for end in ("start", "end"):
            t = [c for c in self.copes if c["end"] == end and c["side"] == "top"]
            b = [c for c in self.copes if c["end"] == end and c["side"] == "bottom"]
            if t and b and t[0]["depth"] + b[0]["depth"] > s["h"] - 40:
                add("error", f"notches at {end}", "top and bottom notches leave too little web")
        return out

    @staticmethod
    def norm_face(face):
        return "v" if face == "h" else face

    def hole_face(self, hole):
        """Face a hole is cut on (DSTV 'h' is the back of the web; angles only have v and u)."""
        face = self.norm_face(hole["face"])
        if self.sec["kind"] == "L" and face not in ("v", "u"):
            face = "u"
        return face

    def _check_hole(self, hole, faces):
        s = self.sec
        out = []

        def add(level, text, ref=""):
            out.append({"level": level, "text": text, "ref": ref})

        face = self.hole_face(hole)
        d = hole["d"]
        k = s["kind"]
        if face == "u" and k in ("I", "U"):
            add("error", "bottom-flange holes can't be reached from above - drill line or turn the part",
                "MACHINE")
            return out
        if face not in faces:
            add("error", f"face '{face}' doesn't exist on this section")
            return out
        thick = s["tf"] if face in ("o", "u") else s["tw"]
        if d < max(UK.MIN_HOLE_MACHINE, thick) - 1e-6:
            add("error", f"{d:.0f} mm is too small to plasma cut in {thick:.1f} mm steel "
                f"(minimum {max(UK.MIN_HOLE_MACHINE, thick):.0f} mm)", "MACHINE")
        length = max(hole.get("slot", 0) or 0, d)
        along = abs(hole.get("angle", 0) or 0) < 45
        half_x = length / 2 if along else d / 2
        half_y = d / 2 if along else length / 2
        c = S.face_to_section(s, face, hole["y"])
        mins = UK.min_distances(d)
        if face == "v":
            lo = (s["tf"] + s["r"]) if k in ("I", "U") else (s["t"] + s["r1"])
            if c - half_y < lo - 1e-6:
                add("error", f"runs into the {'other leg' if k == 'L' else 'flange'} root (the hole edge must be "
                    f"above {lo:.0f} mm)")
            if k in ("I", "U"):
                hi = s["h"] - s["tf"] - s["r"]
                if c + half_y > hi + 1e-6:
                    add("error", f"runs into the flange root (the hole edge must be below {hi:.0f} mm)")
            elif s["h"] - c < mins["e2"] - 1e-6:
                add("error", f"edge distance {s['h'] - c:.0f} mm, minimum {mins['e2']:.0f}",
                    "BS EN 1993-1-8 Table 3.3 (e2 >= 1.2 d0)")
        else:
            if k == "I":
                clear = abs(c) - half_y - (s["tw"] / 2 + s["r"])
                edge = s["b"] / 2 - abs(c)
            else:                                    # channel flange / flat leg of an angle
                web_in = s["b"] / 2 - (s["tw"] if k == "U" else s["t"])
                clear = web_in - (c + half_y) - (s["r"] if k == "U" else s["r1"])
                edge = c + s["b"] / 2
            if clear < -1e-6:
                add("error", "runs into the web root radius" if k == "I" else "runs into the root radius")
            if edge < mins["e2"] - 1e-6:
                add("error", f"edge distance {edge:.0f} mm, minimum {mins['e2']:.0f}",
                    "BS EN 1993-1-8 Table 3.3 (e2 >= 1.2 d0)")
        outline = self.face_outline(face)
        if not inside(outline, hole["x"], hole["y"]):
            add("error", "outside the part (in a notch or past the end)")
        else:
            chains = self.chains(face)
            near = min(_dist_to_polyline(ch["points"], hole["x"], hole["y"]) for ch in chains) if chains else 1e9
            e1 = near - (half_x - d / 2)
            if e1 < mins["e1"] - 1e-6:
                add("error", f"end distance {e1:.0f} mm, minimum {mins['e1']:.0f}",
                    "BS EN 1993-1-8 Table 3.3 (e1 >= 1.2 d0)")
        return out


# ------------------------------------------------------------------ geometry helpers
def _arc(cx, cy, r, a0, a1, steps=4):
    """Points strictly inside an arc (the ends are added by the caller)."""
    if r <= 0:
        return []
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps))) for i in range(1, steps)]


def _dedupe(pts):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-6:
        out.pop()
    return out


def inside(poly, x, y):
    n, c = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def _dist_to_polyline(pts, x, y):
    best = 1e18
    for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L2))
        best = min(best, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
    return best


def x_intervals_inside(poly, y):
    """X ranges where the horizontal line at height y is inside the polygon."""
    xs = []
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def clip_band(poly, y0, y1):
    """The part of a polygon between two heights (Sutherland-Hodgman, for drawing plates)."""
    def clip(pts, keep, cross):
        out = []
        for i in range(len(pts)):
            a, b = pts[i - 1], pts[i]
            if keep(b):
                if not keep(a):
                    out.append(cross(a, b))
                out.append(b)
            elif keep(a):
                out.append(cross(a, b))
        return out

    def at(yc):
        return lambda a, b: (a[0] + (yc - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), yc)

    pts = clip(list(poly), lambda p: p[1] >= y0 - 1e-9, at(y0))
    return clip(pts, lambda p: p[1] <= y1 + 1e-9, at(y1)) if pts else []


# ------------------------------------------------------------------ nesting
class Bar:
    """A stock bar with parts placed along it, the way a beam line cuts them: trim the rough
    mill end, then part after part. Two square ends share one cut; otherwise a small gap is
    left between the parts and falls out as scrap."""

    def __init__(self, section, length, parts):
        self.section_title = section
        self.length = float(length)
        self.parts = parts
        self.placements = []      # {part, copy, x0, x1, start_shared}
        self.scraps = []          # (x0, x1) pieces that fall out
        self.overflow = []        # (part index, copy, reason)
        self.remnant = None
        self._nest()

    def _nest(self):
        x = UK.TRIM
        self.scraps.append((0.0, UK.TRIM))
        prev = None
        for i, p in enumerate(self.parts):
            for k in range(p.qty):
                if p.section_title != self.section_title:
                    self.overflow.append((i, k, f"different section ({p.section_title})"))
                    continue
                if any(issue["level"] == "error" and issue["item"] in ("section", "length") for issue in p.check()):
                    self.overflow.append((i, k, "part has errors"))
                    continue
                shared = prev is not None and prev.end_is_square("end") and p.end_is_square("start")
                start = x if (shared or prev is None) else x + UK.GAP
                if start + p.length > self.length + 1e-6:
                    self.overflow.append((i, k, "doesn't fit on this bar"))
                    continue
                if prev is not None and not shared:
                    self.scraps.append((x, start))
                self.placements.append({"part": i, "copy": k, "x0": start, "x1": start + p.length,
                                        "start_shared": shared})
                x = start + p.length
                prev = p
        if self.length - x > 1e-6:
            self.remnant = (x, self.length)

    def to_dict(self):
        return {"section": self.section_title, "length": self.length, "placements": self.placements,
                "scraps": self.scraps, "remnant": self.remnant,
                "overflow": [{"part": i, "copy": k, "reason": r} for i, k, r in self.overflow],
                "used": sum(pl["x1"] - pl["x0"] for pl in self.placements) / self.length}


def nest_all(parts, stock_length):
    """Put every part on stock bars: one run of bars per section, as many bars as needed."""
    bars = []
    by_section = {}
    for p in parts:
        by_section.setdefault(p.section_title, []).append(p)
    for title, group in by_section.items():
        todo = [Part.from_dict(dict(p.to_dict(), qty=1)) for p in group for _ in range(p.qty)]
        while todo:
            bar = Bar(title, stock_length, todo)
            if not bar.placements:
                break                                    # nothing fits (too long or has errors)
            placed = {pl["part"] for pl in bar.placements}
            bar.parts = todo
            bars.append(bar)
            todo = [p for i, p in enumerate(todo) if i not in placed]
    return bars
