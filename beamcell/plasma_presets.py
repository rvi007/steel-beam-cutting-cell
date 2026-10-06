"""
Saved plasma settings: the numbers that were tried on the real machine and worked.

A cut chart is only a starting point. Plasma behaves differently with every machine, consumable,
gas supply and steel, so the operator tries settings on a test piece, adjusts them, and saves the
ones that cut well - named after the beam, e.g. "UB 305x165x40 S355". Next time the same beam is
cut, the saved file is opened and the planner uses those numbers instead of the chart.

One file per setting, in the plasma_settings/ folder (kept on the machine, not in git):

    {"name", "section", "grade", "process", "consumables", "gas", "rating": good|try|bad, "notes",
     "web": {settings}, "flange": {settings}, "created", "updated"}

A beam has two thicknesses (web and flange), so each file has a row for each. Every cut uses the
row whose thickness is nearest to the steel it is cutting.
"""
import json
import os
import re
import threading
import time

from beamcell import plasma, sections as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(ROOT, "plasma_settings")
_lock = threading.Lock()

# every number in a row: (label, unit, lowest, highest)
ROW = {
    "thickness_mm":       ("Thickness", "mm", 0, 100),
    "amps":               ("Current", "A", 0, 400),
    "speed_mm_min":       ("Cut speed", "mm/min", 10, 15000),
    "hole_speed_mm_min":  ("Hole speed", "mm/min", 10, 15000),
    "corner_speed_pct":   ("Corner speed", "% of cut speed", 10, 100),
    "arc_voltage_v":      ("Arc voltage", "V", 0, 250),
    "cut_height_mm":      ("Cut height", "mm", 0, 20),
    "pierce_height_mm":   ("Pierce height", "mm", 0, 30),
    "pierce_delay_s":     ("Pierce delay", "s", 0, 10),
    "kerf_mm":            ("Kerf width", "mm", 0, 10),
    "gas_pressure_bar":   ("Gas pressure", "bar", 0, 12),
}
THC = ("on", "off")
RATINGS = {"good": "works well", "try": "still trying", "bad": "doesn't work"}
GRADES = ("S275", "S355", "S235", "S420", "S460", "other")
DEFAULT_PRESSURE = {"o2": 5.5, "air": 5.5, "pen": 0.0}


def _num(v, lo, hi, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if not lo <= x <= hi:
        raise ValueError(f"{what} must be between {lo:g} and {hi:g}")
    return round(x, 2)


def safe_name(name):
    name = re.sub(r"[^A-Za-z0-9_. x()-]", " ", str(name))
    name = re.sub(r"\s+", " ", name).strip(". ")[:80]
    if not name:
        raise ValueError("give the settings a name, e.g. the beam: UB 305x165x40 S355")
    return name


def _row_from_chart(thickness, process):
    cut = plasma.settings("cut", thickness, process)
    hole = plasma.settings("hole", thickness, process)
    return {"thickness_mm": round(float(thickness), 1), "amps": cut["amps"], "speed_mm_min": cut["speed_mm_min"],
            "hole_speed_mm_min": hole["speed_mm_min"], "corner_speed_pct": 50, "arc_voltage_v": cut["arc_voltage_v"],
            "cut_height_mm": cut["cut_height_mm"], "pierce_height_mm": cut["pierce_height_mm"],
            "pierce_delay_s": hole["pierce_delay_s"], "kerf_mm": cut["kerf_mm"],
            "gas_pressure_bar": DEFAULT_PRESSURE.get(process, 5.5), "thc": "on"}


def start_values(section, process="o2", grade="S355"):
    """New settings for a beam, filled in from the cut chart - the starting point for trying."""
    s = S.get(section)
    return {"name": f"{section} {grade}", "section": section, "grade": grade, "process": process,
            "consumables": "", "gas": plasma.chart(process)["gas"], "rating": "try", "notes": "",
            "web": _row_from_chart(s["tw"], process), "flange": _row_from_chart(s["tf"], process)}


def clean(data):
    """Check what the screen sent; raises ValueError with a plain message if something is wrong."""
    out = {"name": safe_name(data.get("name", "")),
           "section": str(data.get("section", ""))[:60], "grade": str(data.get("grade", ""))[:20],
           "process": data.get("process", "o2"), "consumables": str(data.get("consumables", ""))[:200],
           "gas": str(data.get("gas", ""))[:80], "rating": data.get("rating", "try"), "notes": str(data.get("notes", ""))[:2000]}
    if out["process"] not in plasma.CHARTS:
        raise ValueError(f"process must be one of {', '.join(plasma.CHARTS)}")
    if out["rating"] not in RATINGS:
        out["rating"] = "try"
    for part in ("web", "flange"):
        row = data.get(part) or {}
        clean_row = {}
        for key, (label, unit, lo, hi) in ROW.items():
            clean_row[key] = _num(row.get(key), lo, hi, f"{part} {label.lower()} ({unit})")
        clean_row["thc"] = row.get("thc") if row.get("thc") in THC else "on"
        out[part] = clean_row
    return out


def _path(name):
    return os.path.join(FOLDER, safe_name(name) + ".json")


def save(data, folder=None):
    """Save (or replace) one setting. Returns what was saved."""
    folder = folder or FOLDER
    d = clean(data)
    path = os.path.join(folder, d["name"] + ".json")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        os.makedirs(folder, exist_ok=True)
        old = _read(path)
        d["created"] = (old or {}).get("created", now)
        d["updated"] = now
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh, indent=1)
        os.replace(tmp, path)
    return d


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load(name, folder=None):
    d = _read(os.path.join(folder or FOLDER, safe_name(name) + ".json"))
    if d is None:
        raise KeyError(f"no saved plasma settings called {name!r}")
    return d


def delete(name, folder=None):
    path = os.path.join(folder or FOLDER, safe_name(name) + ".json")
    if not os.path.exists(path):
        raise KeyError(f"no saved plasma settings called {name!r}")
    os.remove(path)


def entries(folder=None):
    """Every saved setting, newest first: name, section, grade, rating, thicknesses, when."""
    folder = folder or FOLDER
    if not os.path.isdir(folder):
        return []
    out = []
    for f in os.listdir(folder):
        if f.endswith(".json"):
            d = _read(os.path.join(folder, f))
            if d:
                out.append({k: d.get(k, "") for k in ("name", "section", "grade", "process", "rating", "updated")} |
                           {"web_mm": (d.get("web") or {}).get("thickness_mm"), "flange_mm": (d.get("flange") or {}).get("thickness_mm")})
    return sorted(out, key=lambda e: e["updated"], reverse=True)


def for_section(section, folder=None):
    """Saved settings for this beam: the ones marked 'works well' first, then the newest."""
    rank = {"good": 0, "try": 1, "bad": 2}
    match = [e for e in entries(folder) if e["section"] == section]
    return sorted(match, key=lambda e: rank.get(e["rating"], 1))


def apply(proc, preset, feature, thickness):
    """The cut chart's settings for one cut (plasma.settings) with the saved numbers put in."""
    rows = [preset.get("web"), preset.get("flange")]
    row = min((r for r in rows if r), key=lambda r: abs(r["thickness_mm"] - thickness))
    out = dict(proc)
    for k in ("amps", "arc_voltage_v", "cut_height_mm", "pierce_height_mm", "kerf_mm", "gas_pressure_bar"):
        out[k] = row[k]
    if feature in ("hole", "slot"):
        out["speed_mm_min"] = row["hole_speed_mm_min"]
    elif feature == "opening":
        out["speed_mm_min"] = round(row["speed_mm_min"] * plasma.FEATURES["opening"]["speed"])
    else:
        out["speed_mm_min"] = row["speed_mm_min"]
    if "corner_speed_mm_min" in out:
        out["corner_speed_mm_min"] = round(out["speed_mm_min"] * row["corner_speed_pct"] / 100)
    if out.get("pierce_delay_s", 0) > 0:               # edge starts don't pierce
        out["pierce_delay_s"] = row["pierce_delay_s"]
    if row["thc"] == "off":
        out["thc"] = "off (saved setting)"
    out["preset"] = preset.get("name", "")
    return out
