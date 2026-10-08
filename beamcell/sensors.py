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


def thickness_tolerance(t, flange):
    """BS EN 10034 Table 2 thickness tolerances (mm): web s or flange t."""
    if flange:
        rows = [(6.5, (-0.5, 1.5)), (10, (-1.0, 2.0)), (20, (-1.5, 2.5)), (30, (-2.0, 2.5)), (40, (-2.5, 2.5)), (1e9, (-3.0, 3.0))]
    else:
        rows = [(7, (-0.7, 0.7)), (10, (-1.0, 1.0)), (20, (-1.5, 1.5)), (40, (-2.0, 2.0)), (1e9, (-2.5, 2.5))]
    return next(tol for limit, tol in rows if t < limit)


def _sim(seed, lo, hi):
    """A repeatable 'measured' deviation between lo and hi for the simulation."""
    v = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(lo + (hi - lo) * v, 1)


# What the simulated sensors "see" on the bed - the Sensors tab can put a wrong bar there to try the check.
SIM_MODES = {"ok": "the right bar", "short": "a bar too short for the job", "wrong_section": "the wrong section (bigger)",
             "narrow_flange": "a bar with a narrow flange",
             "wrong_web": "a bar with the wrong web (flange right)", "thin_flange": "a bar with a thin flange",
             "existing_hole": "a bar that already has a hole", "bent": "a bent bar", "no_bar": "no bar on the bed"}
SIM_BAR = {"mode": "ok"}


def simulated_reading(s, length_mm, needed_mm=None, x_hole=None):
    """What the simulated sensors measure: small, realistic, repeatable deviations - or the fault
    chosen on the Sensors tab (SIM_BAR)."""
    key = f"{s['title']}|{round(float(length_mm))}"
    tol = tolerances(s, length_mm)
    tw, tf = s.get("tw", s.get("t", 0)), s.get("tf", s.get("t", 0))
    m = {"start_x": _sim(key + "x", -6, 6), "length": length_mm + _sim(key + "L", 0, 8),
         "depth": s["h"] + _sim(key + "h", -1.0, 2.0), "width": s.get("b", s["h"]) + _sim(key + "b", -1.0, 1.5),
         "web": tw + _sim(key + "tw", -0.2, 0.3), "flange": tf + _sim(key + "tf", -0.3, 0.5),
         "out_of_square": _sim(key + "q", 0.2, tol["out_of_square"] * 0.6),
         "bow": _sim(key + "w", 0.5, tol["bow"] * 0.4), "present": True, "holes": []}
    mode = SIM_BAR["mode"]
    if mode == "short":
        m["length"] = round((needed_mm or length_mm) - 120, 1)
    elif mode == "wrong_section":
        m.update(depth=s["h"] + 8.2, width=m["width"] + 1.6, web=tw + 1.2, flange=tf + 3.0)
    elif mode == "wrong_web":
        m["web"] = tw + 1.6
    elif mode == "narrow_flange":
        m["width"] = s.get("b", s["h"]) - 4.5
    elif mode == "thin_flange":
        m["flange"] = tf - 2.2
    elif mode == "existing_hole":
        m["holes"] = [{"x": round(x_hole if x_hole is not None else length_mm / 3), "face": "v", "y": round(s["h"] / 2), "d": 22}]
    elif mode == "bent":
        m["bow"] = round(tol["bow"] * 1.8, 1)
    elif mode == "no_bar":
        m["present"] = False
    return m


def measure_bar(section, length_mm, measured=None, needed_mm=None, x_hole=None):
    """The bar check before cutting. With real sensors, `measured` holds their readings; without,
    the readings are simulated (small, realistic, repeatable deviations).
    Returns the readings, the tolerance checks and the offsets the machine applies."""
    s = section if isinstance(section, dict) else S.get(section)
    tol = tolerances(s, length_mm)
    simulated = measured is None
    if simulated:
        measured = simulated_reading(s, length_mm, needed_mm, x_hole)
    checks = []

    def check(name, value, nominal, lo, hi, unit="mm"):
        dev = value - nominal
        ok = lo - 1e-6 <= dev <= hi + 1e-6
        checks.append({"what": name, "measured": round(value, 1), "nominal": round(nominal, 1), "deviation": round(dev, 1),
                       "allowed": f"{lo:+g} / {hi:+g} {unit}", "ok": ok})

    if not measured.get("present", True):
        return {"ok": False, "simulated": simulated, "error": "no bar on the bed (bar-present photo-eye)", "checks": [],
                "measured": measured, "section": s["title"]}
    check("depth (h)", measured["depth"], s["h"], *tol["depth"])
    check("flange width (b)", measured["width"], s.get("b", s["h"]), *tol["width"])
    if "web" in measured:
        tw = s.get("tw", s.get("t", 0))
        check("web thickness", measured["web"], tw, *thickness_tolerance(tw, False))
    if "flange" in measured:
        tf = s.get("tf", s.get("t", 0))
        check("flange thickness", measured["flange"], tf, *thickness_tolerance(tf, True))
    check("out of square", measured["out_of_square"], 0, 0, tol["out_of_square"])
    check(f"bow over {length_mm / 1000:.1f} m", measured["bow"], 0, 0, tol["bow"])
    if needed_mm is None:
        check("length", measured["length"], length_mm, -5, 50)
    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "simulated": simulated, "section": s["title"], "standard": tol["standard"], "measured": measured,
            "start_x": measured["start_x"], "end_x": round(measured["start_x"] + measured["length"], 1),
            "length": round(measured["length"], 1), "checks": checks,
            "offsets": {"x_mm": measured["start_x"], "depth_mm": round(measured["depth"] - s["h"], 1)},
            "how": ["bar-present photo-eye: a bar is on the bed",
                    "datum laser: finds the bar's start - every cut moves by that much",
                    "Cutter runs along the bar with the profile scanner and the torch camera: real depth, width, "
                    "web and flange thickness, out-of-square, bow, the far end and any holes already in the bar",
                    "torch touch-off before every cut: the real surface, so the cut height is right"],
            "result": ("Bar is within tolerance - every cut is shifted to the real bar" if ok else
                       "Bar is OUT of tolerance - check it before cutting (wrong section, bent bar, or not seated on the rollers)")}


def identify(m, kind=None):
    """Which library section the measured bar is: the nearest on depth, flange width, web and flange
    thickness (all four - a flange alone can't tell a UB 305x165x40 from a 305x165x46)."""
    best, err = None, 1e9
    for rows in S.library().values():
        for s in rows:
            if kind and s["kind"] != kind:
                continue
            tw, tf = s.get("tw", s.get("t", 0)), s.get("tf", s.get("t", 0))
            e = (abs(m["depth"] - s["h"]) / 4 + abs(m["width"] - s.get("b", s["h"])) / 4
                 + abs(m.get("web", tw) - tw) + abs(m.get("flange", tf) - tf))
            if e < err:
                best, err = s, e
    return best["title"] if best else None


def _needed_length(bar):
    """How much steel the job needs: up to its last cut (a piece left on the bed doesn't count)."""
    cut = [pl["x1"] for pl in bar.placements if not pl.get("keep")]
    return max(cut) if cut else 0.0


def job_check(bar, measured=None):
    """The check before Start: measure the bar on the bed, then check it against THIS job -
    the right section, enough length, and every hole still meeting the UK rules on the real steel.
    Returns {ok, problems: [{what, text, fix}], checks, ...}; Start is refused unless ok."""
    from beamcell.parts import Part                # here: parts imports a lot, sensors is imported early
    if not bar.parts:
        return {"ok": True, "problems": [], "checks": [], "needed_mm": 0}
    s = bar.parts[0].sec
    needed = _needed_length(bar)
    first = bar.placements[0] if bar.placements else None
    r = measure_bar(s, bar.length, measured, needed_mm=needed,
                    x_hole=(first["x0"] + first["x1"]) / 2 if first else None)
    problems = []
    if r.get("error"):
        problems.append({"what": "No bar", "text": "No bar was found on the bed.",
                         "fix": "Load the bar and seat it against the end stop, then press Start again."})
        r.update(ok=False, problems=problems, needed_mm=round(needed, 1), time=_now())
        return r
    m = r["measured"]
    r["identified"] = identify(m, s["kind"])
    names = {"depth (h)": "Depth", "flange width (b)": "Flange width", "web thickness": "Web thickness",
             "flange thickness": "Flange thickness", "out of square": "Out of square"}
    for c in r["checks"]:
        if not c["ok"]:
            if c["what"].startswith("bow"):
                problems.append({"what": "Bent bar", "text": f"The bar is bowed {c['measured']} mm; up to {c['allowed'].split('/')[1].strip().lstrip('+')} is allowed.",
                                 "fix": "Straighten the bar, or seat it properly on the rollers, then press Start again."})
            else:
                looks = (f" The measured web and flange look like {r['identified']}."
                         if r["identified"] and r["identified"] != r["section"] else "")
                problems.append({"what": names.get(c["what"], c["what"]),
                                 "text": f"{names.get(c['what'], c['what'])} is {c['measured']} mm; {r['section']} should be {c['nominal']} mm "
                                         f"({c['allowed']}).{looks}",
                                 "fix": "Check the bar is the section the job needs (look at the label / mill cert)."})
    # enough steel?
    have = m["length"]
    r["needed_mm"] = round(needed, 1)
    r["checks"].append({"what": "length for this job", "measured": round(have), "nominal": round(needed),
                        "deviation": round(have - needed, 1), "allowed": "at least what the job needs", "ok": have >= needed - 0.5})
    if have < needed - 0.5:
        problems.append({"what": "Bar too short", "text": f"The job needs {needed:,.0f} mm of steel; this bar is {have:,.0f} mm "
                                                          f"({needed - have:,.0f} mm short).",
                         "fix": "Load a longer bar, or take the last part off the job."})
    # every hole on the real section: the same UK checks as the Parts tab, with the measured sizes
    real = dict(s, h=m["depth"], b=m["width"])
    if "web" in m:
        real["tw" if "tw" in s else "t"] = m["web"]
    if "flange" in m and "tf" in s:
        real["tf"] = m["flange"]
    seen = set()
    for pl in bar.placements:
        part = bar.parts[pl["part"]]
        if part.mark in seen or pl.get("scrap"):
            continue
        seen.add(part.mark)
        nominal_items = {i["item"] for i in part.check() if i["level"] == "error"}
        on_real = Part.from_dict(dict(part.to_dict(), custom=real))
        for i in on_real.check():
            if i["level"] == "error" and i["item"].startswith(("hole", "slot")) and i["item"] not in nominal_items:
                problems.append({"what": f"{part.mark}: {i['item']}",
                                 "text": f"On the real bar: {i['text']}" + (f" ({i['ref']})" if i.get("ref") else "") + ".",
                                 "fix": "The steel is at the edge of its tolerance: use another bar, or move the hole (Parts tab)."})
    # holes already in the bar, where a part will be
    for h in m.get("holes", []):
        inside = next((bar.parts[pl["part"]].mark for pl in bar.placements
                       if pl["x0"] <= h["x"] - m["start_x"] <= pl["x1"] and not pl.get("scrap")), None)
        if inside:
            problems.append({"what": "Hole already in the bar",
                             "text": f"The torch camera found a {h['d']} mm hole at x = {h['x']:,} mm that isn't in this job - "
                                     f"it would end up in part {inside}.",
                             "fix": "This looks like a used bar or an offcut. Use a new bar, or put this one aside."})
    r["ok"] = not problems
    r["problems"] = problems
    r["time"] = _now()
    r["result"] = ("The bar matches the job - every cut is shifted to the real bar" if r["ok"]
                   else f"The bar doesn't match this job ({len(problems)} problem{'s' if len(problems) > 1 else ''})")
    return r


def _now():
    import time
    return time.strftime("%H:%M:%S")
