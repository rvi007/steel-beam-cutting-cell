"""
Steel beams, the job (what to cut), and the torch paths for each feature.

The beam lies along X on the bed, web standing up (an "I" when you look along it):

        top flange    ==========      <- holes/slots from above ("top" face)
                          ||
        web               ||  <-- torch comes in from the +Y side ("web" face)
                          ||
        bottom flange ==========      <- cut with a tilted torch from both sides

Feature types (all sizes in metres, stored as plain dicts so jobs save as JSON):
  hole   {"type": "hole",  "face": "top"/"web", "x": .., "v": .., "d": diameter}
  slot   {"type": "slot",  "face": "top"/"web", "x": .., "v": .., "d": width, "len": length}
  notch  {"type": "notch", "x": end of the part, "side": +1/-1, "w": length, "depth": ..}
           a "cope": top flange and the top of the web removed at a part end.
           side +1 = the notch goes from x towards +X (it belongs to the part on the right).
  cut    {"type": "cut",   "x": ..}   cut to length (all faces)

  v = position across the face: for "top" it's the sideways offset from the web
      centre (+ is towards +Y), for "web" it's the height above the beam bottom.
"""
import json

import numpy as np

from gantry.machine import BEAM_Y, BED_Z

# name: height h, flange width b, web thickness tw, flange thickness tf (metres), kg per metre
PROFILES = {
    "IPE200": dict(h=0.200, b=0.100, tw=0.0056, tf=0.0085, kg_m=22.4),
    "IPE300": dict(h=0.300, b=0.150, tw=0.0071, tf=0.0107, kg_m=42.2),
    "HEA200": dict(h=0.190, b=0.200, tw=0.0065, tf=0.0100, kg_m=42.3),
    "HEB300": dict(h=0.300, b=0.300, tw=0.0110, tf=0.0190, kg_m=117.0),
}

STANDOFF = 0.003      # torch tip height above the steel while cutting
ROOT = 0.015          # keep clear of the rounded corner where web meets flange
EDGE = 0.008          # keep holes this far from a flange edge
STEP = 0.003          # spacing of path points along a cut
DOWN = np.array([0.0, 0.0, -1.0])
SIDE = np.array([0.0, -1.0, 0.0])                    # web, torch from +Y
DIAG_P = np.array([0.0, -1.0, -1.0]) / np.sqrt(2)    # bottom flange, +Y half
DIAG_N = np.array([0.0, 1.0, -1.0]) / np.sqrt(2)     # bottom flange, -Y half


def cut_speed(thickness):
    """Plasma cutting speed (m/s) for a plate thickness (m) - typical 130 A values."""
    mm = thickness * 1000
    return 0.050 if mm <= 6 else 0.040 if mm <= 10 else 0.028 if mm <= 15 else 0.016


class Job:
    def __init__(self, profile="IPE300", length=12.0, features=None):
        self.profile = profile
        self.length = float(length)
        self.features = list(features or [])

    # ---- beam dimensions ----
    @property
    def p(self):
        return PROFILES[self.profile]

    @property
    def z_bot(self):
        return BED_Z

    @property
    def z_top(self):
        return BED_Z + self.p["h"]

    # ---- save / load ----
    def to_json(self):
        return json.dumps({"profile": self.profile, "length": self.length,
                           "features": self.features}, indent=1)

    @classmethod
    def from_json(cls, text):
        data = json.loads(text)
        return cls(data["profile"], data["length"], data["features"])

    # ---- parts ----
    def cuts(self):
        return sorted(f["x"] for f in self.features if f["type"] == "cut")

    def parts(self):
        """List of (x0, x1) pieces the cuts divide the stock into."""
        edges = [0.0] + self.cuts() + [self.length]
        return [(a, b) for a, b in zip(edges[:-1], edges[1:])]

    def part_of(self, f):
        """Index of the part a feature belongs to (a cut belongs to the part on its left)."""
        if f["type"] == "cut":
            x = f["x"] - 1e-6
        elif f["type"] == "notch":
            x = f["x"] + f["side"] * f["w"] / 2
        else:
            x = f["x"]
        for i, (a, b) in enumerate(self.parts()):
            if a <= x < b:
                return i
        return len(self.parts()) - 1

    def notches(self, part):
        """(x_from, x_to, depth) of every notch on this part."""
        out = []
        for f in self.features:
            if f["type"] == "notch" and self.part_of(f) == part:
                xs = sorted([f["x"], f["x"] + f["side"] * f["w"]])
                out.append((xs[0], xs[1], f["depth"]))
        return out

    def weight(self, part):
        a, b = self.parts()[part]
        return self.p["kg_m"] * (b - a)

    # ---- checking ----
    def check(self, f):
        """Return a problem description, or '' if the feature is OK."""
        p, L = self.p, self.length
        t = f["type"]
        inside = 0 <= f["x"] <= L if t == "notch" else 0 < f["x"] < L
        if not inside:
            return "outside the beam"
        if t in ("hole", "slot"):
            r = f["d"] / 2
            half = f.get("len", f["d"]) / 2
            thick = p["tf"] if f["face"] == "top" else p["tw"]
            if f["d"] < max(0.010, 1.2 * thick):
                return f"too small for plasma (min {max(10, 1.2 * thick * 1000):.0f} mm)"
            if f["face"] == "top":
                if abs(f["v"]) - r < p["tw"] / 2 + ROOT:
                    return "too close to the web"
                if abs(f["v"]) + r > p["b"] / 2 - EDGE:
                    return "too close to the flange edge"
            else:
                if f["v"] - r < p["tf"] + ROOT or f["v"] + r > p["h"] - p["tf"] - ROOT:
                    return "too close to a flange"
            for a, b in zip([0.0] + self.cuts(), self.cuts() + [L]):
                if a < f["x"] < b and (f["x"] - half < a + 0.02 or f["x"] + half > b - 0.02):
                    return "too close to the end of the part"
        if t == "notch":
            if not (p["tf"] + ROOT < f["depth"] < p["h"] - p["tf"] - ROOT):
                return "depth must be between the flanges"
            if f["w"] < 0.03:
                return "too short"
        if t == "cut":
            others = [c for c in self.cuts() if c != f["x"]]
            if any(abs(c - f["x"]) < 0.15 for c in others + [0.0, L]):
                return "part shorter than 150 mm"
            for g in self.features:
                if g["type"] in ("hole", "slot") and abs(g["x"] - f["x"]) < g.get("len", g["d"]) / 2 + 0.02:
                    return f"would cut through the {g['type']} at x={g['x']:.3f}"
                if g["type"] == "notch" and g is not f and min(g["x"], g["x"] + g["side"] * g["w"]) \
                        < f["x"] < max(g["x"], g["x"] + g["side"] * g["w"]):
                    return f"would cut through the notch at x={g['x']:.3f}"
        return ""

    def problems(self):
        out = []
        for i, f in enumerate(self.features):
            msg = self.check(f)
            if msg:
                out.append(f"#{i + 1} {f['type']} at x={f['x']:.3f}: {msg}")
        return out

    # ---- 3D shape ----
    def part_boxes(self, part):
        """The part as solid boxes (x0, x1, y0, y1, z0, z1), with notches cut away."""
        x0, x1 = self.parts()[part]
        p = self.p
        yb, zb, zt = BEAM_Y, self.z_bot, self.z_top
        notches = self.notches(part)
        xs = sorted({x0, x1, *[n[0] for n in notches], *[n[1] for n in notches]})
        xs = [x for x in xs if x0 <= x <= x1]
        boxes = [(x0, x1, yb - p["b"] / 2, yb + p["b"] / 2, zb, zb + p["tf"])]   # bottom flange
        for a, b in zip(xs[:-1], xs[1:]):
            depth = max([n[2] for n in notches if n[0] <= a + 1e-9 and b <= n[1] + 1e-9] or [0])
            web_top = zt - p["tf"] if depth == 0 else zt - depth
            boxes.append((a, b, yb - p["tw"] / 2, yb + p["tw"] / 2, zb + p["tf"], web_top))
            if depth == 0:
                boxes.append((a, b, yb - p["b"] / 2, yb + p["b"] / 2, zt - p["tf"], zt))
        return boxes

    def face_point(self, face, x, v):
        """World point on a face, plus the torch direction for that face."""
        if face == "top":
            return np.array([x, BEAM_Y + v, self.z_top + STANDOFF]), DOWN
        return np.array([x, BEAM_Y + self.p["tw"] / 2 + STANDOFF, self.z_bot + v]), SIDE

    # ---- torch paths ----
    def paths(self, f):
        """The cuts needed for one feature: a list of (points Nx3, direction, thickness)."""
        p = self.p
        t = f["type"]
        if t in ("hole", "slot"):
            return [self._hole_path(f)]
        if t == "cut":
            return self._section_cut(f["x"])
        if t == "notch":
            x_n = f["x"] + f["side"] * f["w"]
            zt = self.z_top
            flange = self._line([x_n, BEAM_Y + p["b"] / 2 + 0.01, zt + STANDOFF],
                                [x_n, BEAM_Y - p["b"] / 2 - 0.01, zt + STANDOFF])
            y = BEAM_Y + p["tw"] / 2 + STANDOFF
            r = 0.012  # rounded inside corner, like a real cope
            corner = [x_n - f["side"] * r * (1 - np.cos(a)) for a in np.linspace(0, np.pi / 2, 8)]
            zc = [zt - f["depth"] + r - r * np.sin(a) for a in np.linspace(0, np.pi / 2, 8)]
            web = np.vstack([self._line([x_n, y, zt - p["tf"] + 0.005], [x_n, y, zt - f["depth"] + r]),
                             np.column_stack([corner, [y] * 8, zc]),
                             self._line([x_n - f["side"] * r, y, zt - f["depth"]],
                                        [f["x"] - f["side"] * 0.01, y, zt - f["depth"]])])
            return [(flange, DOWN, p["tf"]), (web, SIDE, p["tw"])]
        raise ValueError(t)

    def _line(self, a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        n = max(2, int(np.ceil(np.linalg.norm(b - a) / STEP)) + 1)
        return a + np.linspace(0, 1, n)[:, None] * (b - a)

    def _hole_path(self, f):
        """Pierce in the middle, lead in to the edge, go round once plus a little overlap."""
        r = f["d"] / 2 - 0.001          # kerf compensation
        half = f.get("len", f["d"]) / 2 - f["d"] / 2   # straight part of a slot
        # outline in face coordinates (u along X, w across the face)
        pts = []
        if half <= 0:
            for a in np.linspace(0, 2 * np.pi + 0.3, int((2 * np.pi * r) / STEP) + 12):
                pts.append((r * np.cos(a), r * np.sin(a)))
        else:
            n_arc = int(np.pi * r / STEP) + 6
            pts += [(half + r * np.cos(a), r * np.sin(a)) for a in np.linspace(-np.pi / 2, np.pi / 2, n_arc)]
            pts += [(u, r) for u in np.linspace(half, -half, int(2 * half / STEP) + 2)]
            pts += [(-half + r * np.cos(a), r * np.sin(a)) for a in np.linspace(np.pi / 2, 3 * np.pi / 2, n_arc)]
            pts += [(u, -r) for u in np.linspace(-half, half + 0.004, int(2 * half / STEP) + 2)]
        start = pts[0]
        lead = [(start[0] * s, start[1] * s) for s in np.linspace(0, 1, 6)]   # from the centre out
        pts = lead + pts
        centre, d = self.face_point(f["face"], f["x"], f["v"])
        if f["face"] == "top":
            world = [centre + [u, w, 0] for u, w in pts]
            thick = self.p["tf"]
        else:
            world = [centre + [u, 0, w] for u, w in pts]
            thick = self.p["tw"]
        return np.array(world), d, thick

    def _section_cut(self, x):
        """Cut the whole profile at x: top flange, web, then each half of the bottom flange."""
        p = self.p
        yb, zb, zt = BEAM_Y, self.z_bot, self.z_top
        s = STANDOFF / np.sqrt(2)
        top = self._line([x, yb + p["b"] / 2 + 0.01, zt + STANDOFF], [x, yb - p["b"] / 2 - 0.01, zt + STANDOFF])
        web = self._line([x, yb + p["tw"] / 2 + STANDOFF, zt - p["tf"] + 0.004],
                         [x, yb + p["tw"] / 2 + STANDOFF, zb + p["tf"] + 0.004])
        # bottom flange: tilted torch, tip on the flange's upper surface
        y_in, y_out = p["tw"] / 2 + 0.006, p["b"] / 2 + 0.01
        z = zb + p["tf"]
        bot_p = self._line([x, yb + y_in + s, z + s], [x, yb + y_out + s, z + s])
        bot_n = self._line([x, yb - y_in - s, z + s], [x, yb - y_out - s, z + s])
        return [(top, DOWN, p["tf"]), (web, SIDE, p["tw"]),
                (bot_p, DIAG_P, p["tf"]), (bot_n, DIAG_N, p["tf"])]


def demo_job(profile="IPE300", length=12.0):
    """A beam cut into parts with holes, slots and notches - sized to fit any profile."""
    p = PROFILES[profile]
    top = round((p["tw"] / 2 + p["b"] / 2) / 2, 3)          # half-way out on the flange
    plasma_min = np.ceil(1.25 * max(p["tf"], p["tw"]) * 1000) / 1000   # smallest clean plasma hole
    room = 2 * (p["b"] / 2 - EDGE - top)                     # biggest hole that fits the flange
    small = round(max(0.018, plasma_min) if room > 0.03 else min(0.014, room), 3)
    small = min(small, round(room - 0.002, 3), round(2 * (top - p["tw"] / 2 - ROOT) - 0.002, 3))
    bolt = max(0.022, plasma_min)
    web_lo = round(p["tf"] + 0.045, 3)
    web_hi = round(p["h"] - p["tf"] - 0.045, 3)
    mid = round(p["h"] / 2, 3)
    cope = round(min(0.05, p["h"] - p["tf"] - 0.03), 3)
    k = length / 12.0                                        # squeeze it onto shorter stock
    f = [
        # Part 1: end-plate bolt holes in the web, a cope at the start
        {"type": "notch", "x": 0.0, "side": 1, "w": 0.12, "depth": cope},
        {"type": "hole", "face": "web", "x": 0.2, "v": web_lo, "d": bolt},
        {"type": "hole", "face": "web", "x": 0.2, "v": web_hi, "d": bolt},
        {"type": "hole", "face": "top", "x": round(1.2 * k, 3), "v": top, "d": small},
        {"type": "hole", "face": "top", "x": round(1.2 * k, 3), "v": -top, "d": small},
        {"type": "cut", "x": round(2.4 * k, 3)},
        # Part 2: slotted holes for adjustment + a big web penetration for a pipe
        {"type": "slot", "face": "top", "x": round(3.0 * k, 3), "v": top, "d": small, "len": 0.045},
        {"type": "slot", "face": "top", "x": round(3.0 * k, 3), "v": -top, "d": small, "len": 0.045},
        {"type": "hole", "face": "web", "x": round(3.9 * k, 3), "v": mid,
         "d": round(min(0.08, p["h"] - 2 * p["tf"] - 0.05), 3)},
        {"type": "slot", "face": "top", "x": round(4.8 * k, 3), "v": top, "d": small, "len": 0.045},
        {"type": "slot", "face": "top", "x": round(4.8 * k, 3), "v": -top, "d": small, "len": 0.045},
        {"type": "cut", "x": round(5.4 * k, 3)},
        # Part 3: coped at both ends with cleat holes (a typical secondary beam)
        {"type": "notch", "x": round(5.4 * k, 3), "side": 1, "w": 0.1, "depth": cope},
        {"type": "hole", "face": "web", "x": round(5.4 * k + 0.06, 3), "v": mid, "d": bolt},
        {"type": "hole", "face": "web", "x": round(8.0 * k - 0.06, 3), "v": mid, "d": bolt},
        {"type": "notch", "x": round(8.0 * k, 3), "side": -1, "w": 0.1, "depth": cope},
        {"type": "cut", "x": round(8.0 * k, 3)},
        # Part 4, then a short remnant
        {"type": "hole", "face": "top", "x": round(9.75 * k, 3), "v": top, "d": small},
        {"type": "hole", "face": "top", "x": round(9.75 * k, 3), "v": -top, "d": small},
        {"type": "hole", "face": "web", "x": round(11.4 * k, 3), "v": web_lo, "d": bolt},
        {"type": "hole", "face": "web", "x": round(11.4 * k, 3), "v": web_hi, "d": bolt},
        {"type": "cut", "x": round(11.5 * k, 3)},
    ]
    return Job(profile, length, f)
