"""
Every sensor the cell has, or will have. A sensor that isn't fitted yet is SIMULATED: it answers
like the real one would, so the rest of the software (planning, safety, the screens) is ready
for the day it is wired in. Each one says what it is for, where it goes and what to buy.

The bar check (measure_bar) is what real beam lines do before cutting. A rolled beam is never
exactly its catalogue size, or exactly where it was put:
  - BS EN 10034 lets an I/H section be a few mm deeper or wider, out of square, and bowed by up
    to 0.1-0.3 % of its length (18 mm over 12 m for a UB 305),
  - the crane never puts the bar down at exactly x = 0.
So the machine finds the bar's ends and measures its real profile, then shifts every cut to the
real steel. Production lines do it with a laser scanner on the robot (Ficep NOZOMI), a measuring
sensor on the torch (Voortman V808) or a measuring stand (Lincoln Electric PythonX); the torch can
also touch the steel ("ohmic touch sensing").
"""
import hashlib

from beamcell import sections as S
from beamcell.config import CONFIG

# id: (group, name, what it tells the machine, where it goes, real-life examples, interface, safety rated?)
SENSORS = {
    # ---- the two cameras
    "cam_cell": ("vision", "Camera 1 - cell overview",
                 "people in the warning / danger zones (YOLO), objects left on the bed, a part hanging or slipping, "
                 "offcuts stuck in the rollers, smoke",
                 "high on the infeed-end column, looking down the whole cell",
                 "Logitech C920 / Arducam USB wide-angle (prototype); IP67 industrial GigE camera (full size)", "USB / CSI", False),
    "cam_torch": ("vision", "Camera 2 - close-up on the torch",
                  "where the bar edge really is, the cut line and kerf, hole quality, nozzle wear, the pen mark on the prototype",
                  "on the Cutter, beside the torch, behind a spatter shield",
                  "Arducam IMX219 (prototype); welding camera with auto-darkening, e.g. Xiris / Cavitar (full size)", "CSI / USB", False),
    # ---- finding the bar
    "bar_present": ("bar", "Bar-present photo-eye",
                    "a bar is on the bed (the cut can't start on an empty bed)",
                    "across the bed at the infeed end, just above the rollers",
                    "IR break-beam pair (prototype); SICK W12 / Omron E3Z through-beam (full size)", "GPIO", False),
    "datum_laser": ("bar", "Datum laser (bar start)",
                    "how far the bar's start is from x = 0 - every cut is shifted by this",
                    "on the end stop at the infeed end, looking along the bar",
                    "VL53L1X time-of-flight (prototype); SICK DT50 / Keyence LR-T laser distance (full size)", "I2C / analogue 4-20 mA", False),
    "profile_scanner": ("bar", "Laser profile scanner on the Cutter",
                        "the bar's real depth, flange width, out-of-square and bow, and where its far end is (as the gantry passes)",
                        "on the Cutter's carriage, looking down across the bar",
                        "camera 2 + a line laser (prototype); Micro-Epsilon scanCONTROL / Keyence LJ-X (full size)", "Ethernet", False),
    "gantry_encoders": ("bar", "Gantry position encoders",
                        "where each hand is to 0.1 mm - with the scanner, this measures the bar's length",
                        "on every motor (and a linear scale on the long axis for the full-size cell)",
                        "stepper step count + home switches (prototype); servo encoders + linear scale (full size)", "motion controller", False),
    # ---- the torch
    "torch_touch": ("torch", "Torch touch-off (initial height sensing)",
                    "the true steel surface at every cut: the nozzle touches the steel and closes a small circuit (ohmic contact)",
                    "in the torch (the nozzle / shield circuit) - on the prototype, a micro-switch on the sprung pen holder",
                    "micro-switch on the pen holder (prototype); ohmic contact in the plasma height controller (full size)", "GPIO / THC", False),
    "arc_voltage": ("torch", "Arc voltage (torch height control)",
                    "holds the cut height during the cut: higher torch = higher arc voltage",
                    "in the plasma power source, read by the torch height controller",
                    "(prototype: not needed - pen); Hypertherm Sensor THC or the THC in the plasma system (full size)", "THC", False),
    "torch_breakaway": ("torch", "Torch breakaway (collision) switch",
                        "the torch hit something - stop at once",
                        "the magnetic torch mount on the Cutter",
                        "the pen holder snaps off a magnet + switch (prototype); magnetic breakaway mount (full size)", "GPIO (safety input)", True),
    "arc_ok": ("torch", "Arc OK signal",
               "the arc has transferred to the steel - motion may start; lost arc = stop the cut and retry once",
               "from the plasma power source", "(prototype: not needed); plasma system 'arc transfer' output (full size)", "digital input", False),
    # ---- the Handler
    "magnet_current": ("handler", "Magnet current monitor",
                       "the magnet is really ON and at full strength - a drop means it's losing its grip",
                       "in the magnet's supply", "INA219 current sensor (prototype); magnet controller with monitoring (full size)", "I2C / digital", False),
    "load_cell": ("handler", "Load cell under the magnet",
                  "the weight of the part it is holding: too light = slipping or the wrong part, too heavy = not cut free",
                  "between the Handler's wrist and the magnet",
                  "1 kg load cell + HX711 (prototype); 1 t load pin (full size)", "GPIO / analogue", False),
    "magnet_battery": ("handler", "Magnet battery backup",
                       "the battery that keeps the magnet on if the power goes (BS EN 13155) - charge level",
                       "in the magnet controller", "(prototype: not needed at 5 V); magnet controller with battery backup (full size)", "digital", False),
    # ---- the cell (safety and environment)
    "light_curtain": ("safety", "Light curtain at the loading side",
                      "someone reaching into the cell - protective stop", "along the operator side of the fence",
                      "IR break-beam demo (prototype); Type 4 light curtain, e.g. SICK deTec4 (full size)", "safety relay", True),
    "area_scanner": ("safety", "Safety laser scanner",
                     "someone walking into the cell floor - slow down, then stop", "at floor level in two corners of the cell",
                     "(prototype: camera 1 instead); SICK microScan3 / Pilz PSENscan (full size)", "safety relay / PLC", True),
    "gate_switch": ("safety", "Gate interlock", "the gate is shut", "on the gate", "coded magnetic safety switch", "safety relay", True),
    "estop": ("safety", "Emergency stops", "stop everything now", "at the panel, each end of the cell and on the pendant",
              "40 mm red mushroom, 2 NC contacts", "safety relay", True),
    "fume_flow": ("environment", "Fume extraction airflow", "the extraction is really pulling air - no plasma without it",
                  "in the extraction duct", "airflow / pressure switch", "digital", False),
    "fire_detector": ("environment", "Flame / smoke detector", "a fire in the scrap tray or on the bed - torch off, stop, alarm",
                      "above the scrap tray and the cutting area", "IR flame sensor module (prototype); UV/IR flame detector (full size)", "digital", False),
}

GROUPS = {"vision": "Cameras", "bar": "Finding and measuring the bar", "torch": "The torch",
          "handler": "The Handler (magnet)", "safety": "Safety devices", "environment": "Fumes and fire"}


def status(vision_status=None):
    """Every sensor with its state: 'connected' (working), 'simulated' (not fitted - the software
    pretends), or 'not fitted'."""
    cfg = CONFIG.get("sensors", {})
    simulate = cfg.get("simulate", True)
    out = []
    for sid, (group, name, what, where, buy, interface, safety) in SENSORS.items():
        st = "simulated" if simulate else "not fitted"
        if sid == "cam_cell" and vision_status and vision_status.get("enabled"):
            st = "connected" if vision_status.get("has_frame") else "starting"
        if sid == "cam_torch" and cfg.get("torch_camera"):
            st = "configured"
        out.append({"id": sid, "group": group, "group_name": GROUPS[group], "name": name, "what": what, "where": where,
                    "buy": buy, "interface": interface, "safety_rated": safety, "state": st})
    return out


# ---------------------------------------------------------------------------- the bar check
def tolerances(s, length_mm):
    """Rolling tolerances (mm) for a section - BS EN 10034 for I and H sections. Channels
    (BS EN 10279) and angles (BS EN 10056-2) are close; the I/H values are used for them too."""
    h, b = s["h"], s.get("b", s["h"])
    dh = (-2, 3) if h <= 180 else (-2, 4) if h <= 400 else (-3, 5) if h <= 700 else (-5, 5)
    db = (-1, 4) if b <= 110 else (-2, 4) if b <= 210 else (-4, 4) if b <= 325 else (-5, 6)
    square = 1.5 if b <= 110 else min(0.02 * b, 6.5)
    bow = length_mm * (0.0030 if h <= 180 else 0.0015 if h <= 360 else 0.0010)
    return {"depth": dh, "width": db, "out_of_square": round(square, 1), "bow": round(bow, 1),
            "standard": "BS EN 10034" if s["kind"] == "I" else "BS EN 10034 values (check BS EN 10279 / 10056-2)"}


def _sim(seed, lo, hi):
    """A repeatable 'measured' deviation between lo and hi for the simulation."""
    v = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(lo + (hi - lo) * v, 1)


def measure_bar(section, length_mm, measured=None):
    """The bar check before cutting. With real sensors, `measured` holds their readings; without,
    the readings are simulated (small, realistic, repeatable deviations).
    Returns the readings, the tolerance checks and the offsets the machine applies."""
    s = S.get(section)
    tol = tolerances(s, length_mm)
    key = f"{s['title']}|{round(float(length_mm))}"
    simulated = measured is None
    if simulated:
        measured = {"start_x": _sim(key + "x", -6, 6), "length": length_mm + _sim(key + "L", -3, 8),
                    "depth": s["h"] + _sim(key + "h", -1.0, 2.0), "width": s.get("b", s["h"]) + _sim(key + "b", -1.0, 1.5),
                    "out_of_square": _sim(key + "q", 0.2, tol["out_of_square"] * 0.6),
                    "bow": _sim(key + "w", 0.5, tol["bow"] * 0.4), "present": True}
    checks = []

    def check(name, value, nominal, lo, hi, unit="mm"):
        dev = value - nominal
        ok = lo - 1e-6 <= dev <= hi + 1e-6
        checks.append({"what": name, "measured": round(value, 1), "nominal": round(nominal, 1), "deviation": round(dev, 1),
                       "allowed": f"{lo:+g} / {hi:+g} {unit}", "ok": ok})

    if not measured.get("present", True):
        return {"ok": False, "simulated": simulated, "error": "no bar on the bed (bar-present photo-eye)", "checks": []}
    check("depth (h)", measured["depth"], s["h"], *tol["depth"])
    check("flange width (b)", measured["width"], s.get("b", s["h"]), *tol["width"])
    check("out of square", measured["out_of_square"], 0, 0, tol["out_of_square"])
    check(f"bow over {length_mm / 1000:.1f} m", measured["bow"], 0, 0, tol["bow"])
    check("length", measured["length"], length_mm, -5, 50)
    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "simulated": simulated, "section": s["title"], "standard": tol["standard"],
            "start_x": measured["start_x"], "end_x": round(measured["start_x"] + measured["length"], 1),
            "length": round(measured["length"], 1), "checks": checks,
            "offsets": {"x_mm": measured["start_x"], "depth_mm": round(measured["depth"] - s["h"], 1)},
            "how": ["bar-present photo-eye: a bar is on the bed",
                    "datum laser: finds the bar's start - every cut moves by that much",
                    "Cutter runs along the bar with the profile scanner: real depth, width, out-of-square, bow and the far end",
                    "torch touch-off before every cut: the real surface, so the cut height is right"],
            "result": ("Bar is within tolerance - every cut is shifted to the real bar" if ok else
                       "Bar is OUT of tolerance - check it before cutting (wrong section, bent bar, or not seated on the rollers)")}
