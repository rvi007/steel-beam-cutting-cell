"""
Manual cutting: the operator says what to cut on a bar, right now - no NC1 file, no part list.

A manual job is one stock bar on the bed plus a list of cuts (all sizes in mm, x from the bar's start):

    {"type": "hole",  "face": "v" | "o", "x", "y", "d", "slot": 0, "angle": 0}
          a hole or slot; y across the face like an NC1 file (web: up from the underside,
          flange: from the front edge). Leave y out to put it on the centre line.
    {"type": "cut",   "x", "angle": 0}
          cut right through the section at x - square, or mitred in the web (degrees)
    {"type": "notch", "x", "side": "top" | "bottom", "on": "after" | "before", "length", "depth", "radius": 10}
          a notch (cope) at a cut (or at the bar's start, x = 0), on the piece after or before it

The cuts split the bar into pieces, cut in order from the start like the job planner:
  - every piece except the last is carried to the outfeed table by the Handler,
  - a piece shorter than 150 mm falls into the scrap tray,
  - the last piece (the rest of the bar) stays on the rollers.
The same UK checks, planner, collision check and safety rules are used as for a job.
"""
import math

from beamcell import machine as M
from beamcell import sections as S
from beamcell import uk_codes as UK
from beamcell.parts import Part

CUT_TYPES = ("hole", "cut", "notch")


class ManualBar:
    """Looks like parts.Bar to the planner, but the pieces are where the operator put the cuts."""

    def __init__(self, section, length, pieces):
        self.section_title = section
        self.length = float(length)
        self.parts = [p for p, _, _ in pieces]
        self.placements = []
        for i, (part, x0, x1) in enumerate(pieces):
            last = i == len(pieces) - 1
            self.placements.append({"part": i, "copy": 0, "x0": x0, "x1": x1,
                                    # the start is the mill end or the previous piece's cut - unless it has a
                                    # notch, which needs its own start cut
                                    "start_shared": not any(c["end"] == "start" for c in part.copes),
                                    "keep": last, "scrap": part.length < UK.MIN_PART_LENGTH})
        self.scraps = []
        self.overflow = []
        self.remnant = None

    def to_dict(self):
        return {"section": self.section_title, "length": self.length, "placements": self.placements,
                "scraps": [], "remnant": None, "overflow": [], "manual": True,
                "used": sum(pl["x1"] - pl["x0"] for pl in self.placements if not pl["keep"]) / self.length}


def build(section, length, cuts):
    """(ManualBar, problems). problems: [{level, item, text, ref}] - errors stop the plan."""
    problems = []

    def bad(item, text, ref="", level="error"):
        problems.append({"level": level, "item": item, "text": text, "ref": ref})

    try:
        s = S.get(section)
    except KeyError:
        return None, [{"level": "error", "item": "section", "text": f"unknown section {section!r}", "ref": ""}]
    if s["kind"] not in S.CUTTABLE:
        return None, [{"level": "error", "item": "section", "text": "this cell cuts I, channel and angle sections", "ref": "MACHINE"}]
    length = float(length)
    longest = M.WORK_LENGTH * 1000
    if not 300 <= length <= longest:
        bad("bar", f"bar length must be 300 to {longest:.0f} mm (the {M.WORK_LENGTH:g} m machine)")
        return None, problems
    tan_web_max = math.tan(math.radians(60))

    # where the bar is cut through (sorted), and what angle
    cut_list = []
    for i, c in enumerate(cuts):
        if c.get("type") not in CUT_TYPES:
            bad(f"cut {i + 1}", f"unknown type {c.get('type')!r}")
        elif c["type"] == "cut":
            x, a = float(c["x"]), float(c.get("angle", 0) or 0)
            reach = abs(math.tan(math.radians(a))) * s["h"] / 2
            if abs(math.tan(math.radians(a))) > tan_web_max:
                bad(f"cut {i + 1}", "mitre angle must be within 60 degrees")
            elif not reach < x < length - reach:
                bad(f"cut {i + 1}", f"x = {x:.0f} is outside the bar")
            else:
                cut_list.append((x, a))
    cut_list.sort()
    for (xa, aa), (xb, ab) in zip(cut_list, cut_list[1:]):
        ra = abs(math.tan(math.radians(aa))) * s["h"] / 2
        rb = abs(math.tan(math.radians(ab))) * s["h"] / 2
        if xb - xa < ra + rb + 10:
            bad(f"cuts at {xa:.0f} and {xb:.0f}", "too close together")
    if any(p["level"] == "error" for p in problems):
        return None, problems

    # pieces between the cuts; a mitred cut is shared: the piece before ends on it, the piece after starts on it
    pieces = []
    edges = [(0.0, 0.0)] + cut_list + [(length, 0.0)]
    for i in range(len(edges) - 1):
        (xa, aa), (xb, ab) = edges[i], edges[i + 1]
        ra = math.tan(math.radians(aa)) * s["h"] / 2
        rb = math.tan(math.radians(ab)) * s["h"] / 2
        x0 = xa - abs(ra)
        x1 = xb + abs(rb)
        # a mitred cut is one straight line: the piece before ends with +a, the piece after starts
        # with -a, and both reach |tan a| * h/2 past x so the line crosses x at mid-depth
        mitres = {}
        if aa:
            mitres["start"] = {"web": -aa, "flange": 0.0}
        if ab:
            mitres["end"] = {"web": ab, "flange": 0.0}
        part = Part(f"M{i + 1}", s["title"], x1 - x0, 1, mitres=mitres, source="manual cut")
        pieces.append([part, x0, x1])

    def piece_at(x):
        for k, (part, x0, x1) in enumerate(pieces):
            if x0 <= x < x1:
                return k
        return len(pieces) - 1

    for i, c in enumerate(cuts):
        if c.get("type") == "hole":
            k = piece_at(float(c["x"]))
            part, x0, _ = pieces[k]
            face = c.get("face", "v")
            hole = {"face": face, "x": float(c["x"]) - x0, "d": float(c.get("d", 22)),
                    "y": float(c["y"]) if c.get("y") not in (None, "") else centre_line(s, face)}
            if c.get("slot"):
                hole["slot"] = float(c["slot"])
                hole["angle"] = float(c.get("angle", 0) or 0)
            hole["_cut"] = i
            part.holes.append(hole)
        elif c.get("type") == "notch":
            x = float(c["x"])
            at = [k for k, (xc, _) in enumerate(cut_list) if abs(xc - x) < 1]
            if x < 1:
                k, end = 0, "start"
            elif at:
                k, end = (at[0] + 1, "start") if c.get("on", "after") == "after" else (at[0], "end")
            else:
                bad(f"cut {i + 1}", "a notch goes at a cut (or at the bar start, x = 0) - add the cut first")
                continue
            pieces[k][0].copes.append({"end": end, "side": c.get("side", "top"), "length": float(c["length"]),
                                       "depth": float(c["depth"]), "radius": float(c.get("radius", UK.DEFAULT_COPE_RADIUS))})

    # UK checks on every piece; problems name the operator's cut, not the internal piece
    for k, (part, x0, x1) in enumerate(pieces):
        last = k == len(pieces) - 1
        for issue in part.check():
            if issue["item"] == "length" and (last or part.length < UK.MIN_PART_LENGTH):
                continue                             # short pieces just fall into the scrap tray
            item = issue["item"]
            if item.startswith("hole "):                 # "hole 3" -> the operator's own cut number
                item = f"cut {part.holes[int(item.split()[1]) - 1]['_cut'] + 1} (hole)"
            else:
                item = f"piece {k + 1}: {item}"
            problems.append(dict(issue, item=item))
        if part.length < UK.MIN_PART_LENGTH and not last:
            bad(f"piece {k + 1}", f"{part.length:.0f} mm long - too short to hold, it will fall into the scrap tray",
                level="warning")
    for part, _, _ in pieces:
        for h in part.holes:
            h.pop("_cut", None)
    return ManualBar(s["title"], length, [tuple(p) for p in pieces]), problems


def centre_line(s, face):
    """Middle of a face (DSTV y): mid-depth of the web, middle of a flange, 50 mm back mark on angle legs."""
    if s["kind"] == "L":
        return min(50.0, s["h"] / 2) if face == "v" else min(50.0, s["b"] / 2)
    if face in ("v", "h"):
        return s["h"] / 2
    return s["b"] / 2
