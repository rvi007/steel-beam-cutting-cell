"""
Plasma process settings: what the torch does for each kind of cut, from the plate thickness.

How a real plasma cut runs (and what each number below is for):
  1. Initial height sensing (IHS): the torch moves down until it touches the steel - the nozzle /
     shield closes a small circuit with the plate ("ohmic contact"), or the Z axis feels the stall.
     That finds the true surface, whatever the mill tolerance or bow of the beam.
  2. It lifts to the PIERCE HEIGHT (about 2x the cut height, so molten splash misses the nozzle),
     fires the arc and waits the PIERCE DELAY until it is through the plate.
     A cut that starts at the edge of a flange ("edge start") needs no pierce at all.
  3. It drops to the CUT HEIGHT and moves at the CUT SPEED.
  4. Torch height control (THC): the arc voltage rises when the torch is higher and falls when it
     is lower, so the controller holds the ARC VOLTAGE at its target and so holds the height.
     THC is switched OFF on holes, tight corners and near edges, where the voltage jumps for
     other reasons - the torch would dive into the steel.
  5. Holes: bolt-ready holes need their own recipe (slower, lead-in from the centre, arc off at
     the right moment). Plasma makes good holes down to about diameter = thickness; smaller than
     that they must be drilled. BS EN 1090-2 allows thermal-cut holes if the cut quality and
     hardness requirements are met and the process is qualified.

THE NUMBERS BELOW ARE TYPICAL VALUES FOR PLANNING, built from published cut charts for mild steel.
Before cutting real steel, replace them with the cut chart of YOUR plasma system and consumables
(config/cell.toml, [plasma]) and qualify the process (BS EN ISO 9013 cut quality, BS EN 1090-2).
"""
import numpy as np

# process -> amps -> rows of (thickness mm, speed mm/min, arc volts, cut height mm, pierce height mm,
#                             pierce delay s, kerf mm)
CHARTS = {
    "o2": {                             # O2 plasma, air shield (production machines, e.g. XPR / HPR class)
        "label": "O2 plasma / air shield, mild steel",
        "gas": "O2 plasma, air shield",
        130: [(3, 6500, 125, 2.8, 5.6, 0.1, 2.0), (6, 4300, 128, 3.0, 6.0, 0.3, 2.2), (10, 2700, 135, 3.0, 6.6, 0.5, 2.5),
              (12, 2200, 138, 3.0, 7.0, 0.6, 2.6), (20, 1150, 148, 3.3, 7.6, 1.0, 2.9)],
        170: [(6, 5100, 130, 3.0, 6.3, 0.3, 2.5), (12, 3050, 140, 3.3, 7.0, 0.5, 2.8), (20, 1700, 150, 3.5, 8.0, 0.8, 3.0),
              (25, 1175, 155, 3.5, 8.5, 1.0, 3.2), (32, 700, 162, 3.8, 9.5, 1.5, 3.5)],
        300: [(12, 3950, 145, 3.6, 7.5, 0.4, 3.4), (25, 1950, 160, 4.0, 9.0, 0.8, 3.8), (38, 1000, 170, 4.3, 10.5, 1.5, 4.2),
              (50, 560, 178, 4.5, 11.5, 2.5, 4.6)],
        "choose": [(12, 130), (25, 170), (999, 300)],      # up to 12 mm: 130 A, up to 25 mm: 170 A, then 300 A
        "max_pierce": 50,
    },
    "air": {                            # air plasma (smaller machines, e.g. Powermax class)
        "label": "Air plasma, mild steel",
        "gas": "air",
        45: [(3, 2800, 128, 1.5, 3.8, 0.2, 1.5), (6, 1250, 132, 1.5, 3.8, 0.5, 1.6), (10, 550, 138, 1.5, 3.8, 0.8, 1.8)],
        65: [(6, 2500, 128, 1.5, 3.8, 0.4, 1.7), (10, 1300, 132, 1.5, 3.8, 0.6, 1.8), (12, 1000, 135, 1.5, 3.8, 0.8, 1.9),
             (20, 400, 145, 1.5, 3.8, 1.5, 2.1)],
        "choose": [(6, 45), (999, 65)],
        "max_pierce": 16,
    },
    "pen": {                            # the 1:10 prototype: a pen marks the cut lines
        "label": "Pen marker (1:10 prototype)",
        "gas": "-",
        0: [(0, 1500, 0, 0.0, 2.0, 0.0, 0.5), (100, 1500, 0, 0.0, 2.0, 0.0, 0.5)],
        "choose": [(999, 0)],
        "max_pierce": 999,
    },
}

# how each kind of cut changes the basic settings
FEATURES = {
    "cut":     {"name": "straight cut through the section", "speed": 1.00, "thc": "on (off near the edges)", "start": "edge start - no pierce"},
    "cope":    {"name": "notch (cope) with a radius",        "speed": 1.00, "thc": "on along the straights, off in the corners and radius",
                "start": "edge start - no pierce", "corner": 0.5},
    "hole":    {"name": "bolt hole",                         "speed": 0.60, "thc": "off", "start": "pierce in the centre, lead-in arc"},
    "slot":    {"name": "slotted hole",                      "speed": 0.65, "thc": "off", "start": "pierce in the centre, lead-in arc"},
    "opening": {"name": "opening / cut-out",                 "speed": 0.80, "thc": "on along the straights, off in the corners",
                "start": "pierce inside the waste, lead-in", "corner": 0.5},
}


def chart(process):
    if process not in CHARTS:
        raise ValueError(f"plasma process must be one of {', '.join(CHARTS)}")
    return CHARTS[process]


def amps_for(thickness, process="o2"):
    c = chart(process)
    return next(a for limit, a in c["choose"] if thickness <= limit)


def base(thickness, process="o2"):
    """Interpolated cut-chart row for a thickness (mm)."""
    c = chart(process)
    amps = amps_for(thickness, process)
    rows = np.array(c[amps], float)
    t = float(np.clip(thickness, rows[0, 0], rows[-1, 0]))
    v = [float(np.interp(t, rows[:, 0], rows[:, i])) for i in range(1, 7)]
    return {"process": process, "label": c["label"], "gas": c["gas"], "amps": amps, "thickness_mm": round(float(thickness), 1),
            "speed_mm_min": round(v[0]), "arc_voltage_v": round(v[1]), "cut_height_mm": round(v[2], 1),
            "pierce_height_mm": round(v[3], 1), "pierce_delay_s": round(v[4], 2), "kerf_mm": round(v[5], 1)}


def settings(feature, thickness, process="o2", hole_d=None):
    """Settings for one cut: the cut chart row, changed for the kind of cut (FEATURES), plus warnings."""
    if feature in ("start", "end"):
        feature = "cut"
    f = FEATURES[feature]
    s = base(thickness, process)
    s.update(feature=feature, feature_name=f["name"], thc=f["thc"], start=f["start"],
             speed_mm_min=round(s["speed_mm_min"] * f["speed"]))
    if "corner" in f:
        s["corner_speed_mm_min"] = round(s["speed_mm_min"] * f["corner"])
    if f["start"].startswith("edge"):
        s["pierce_delay_s"] = 0.0
    warnings = []
    if process != "pen" and thickness > chart(process)["max_pierce"] and not f["start"].startswith("edge"):
        warnings.append(f"{thickness:.0f} mm is too thick to pierce - start from an edge or drill a start hole")
    if feature in ("hole", "slot") and hole_d and process != "pen":
        ratio = hole_d / thickness
        s["d_over_t"] = round(ratio, 2)
        if ratio < 1.0:
            warnings.append(f"hole {hole_d:.0f} mm in {thickness:.0f} mm plate (d/t {ratio:.1f}) is smaller than the plate is thick - "
                            "plasma can't make it bolt-ready: drill it")
        elif ratio < 1.5:
            s["note"] = (f"hole d/t {ratio:.1f}: needs the bolt-hole recipe (slow, centre pierce, arc off on time) - check the first one")
    s["warnings"] = warnings
    return s


def speed_m_s(feature, thickness, process="o2"):
    """Cut speed for the planner (m/s)."""
    return settings(feature, thickness, process)["speed_mm_min"] / 60000.0


def pierce_s(feature, thickness, process="o2"):
    return settings(feature, thickness, process)["pierce_delay_s"]


def table(process="o2", thicknesses=(6, 10, 15, 20, 25, 32, 40)):
    """The cut chart for the screen: every feature at each thickness."""
    return {"process": process, "label": chart(process)["label"], "features": FEATURES,
            "rows": [settings(f, t, process) for t in thicknesses for f in ("cut", "hole")]}
