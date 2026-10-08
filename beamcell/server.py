"""
The web server: serves the app in web/ and a small JSON API. Python standard library only
(plus numpy), so it runs on the Jetson as it is.

    python3 -m beamcell.server            # then open http://localhost:8080
    python3 -m beamcell.server --port 8000 --camera 0

API (all JSON):
    GET  /api/info                  machine, UK code tables, section families, system info
    GET  /api/sections              every section in the UK library (sizes)
    GET  /api/section?title=...     one section with its exact outline and plates
    GET  /api/examples              example NC1 files;  GET /api/examples/<file> -> parsed part
    POST /api/nc1                   {filename, text} -> part + import report + checks
    POST /api/nc1/export            {part} -> NC1 text
    POST /api/part                  {part} -> checks, face outlines, weight
    POST /api/nest                  {parts, stock_length} -> bars
    POST /api/machine-size          {length_m: 12 | 20} -> change the machine's length (remembered in config/machine.json)
    POST /api/plan                  {parts, stock_length, bar} -> motion plan for one bar
    POST /api/manual/check          {section, length, cuts} -> pieces + UK checks for a manual cut
    POST /api/manual/plan           {section, length, cuts} -> motion plan for the manual cuts
    GET  /api/prototype             the 1:10 prototype: shopping list with part numbers + every position
    GET  /api/cad                   the CAD files in cad/;  GET /cad/<file> downloads one
    POST /api/cad/part              {part} -> STEP solid of the part (needs CadQuery: a PC, not the Jetson)
    GET  /api/jobs, GET/POST /api/jobs/<name>   saved jobs (jobs/ folder); POST /api/jobs-delete/<name> deletes one
    GET  /api/sensors               every sensor (camera 1 + 2, bar, torch, Handler, safety), and every stop's decisions
    POST /api/sensors/measure       {section, length[, measured]} -> the bar check (BS EN 10034 tolerances)
    GET  /api/plasma[?process=o2]   the plasma cut chart; POST /api/plasma/settings {feature, thickness[, d]}
    GET  /api/plasma/presets        saved plasma settings (plasma_settings/ folder); GET /api/plasma/presets/<name> one;
                                    POST /api/plasma/presets {settings} saves; POST /api/plasma/presets-delete/<name>
    GET  /api/plasma/start?section=&process=&grade=   new settings for a beam, from the cut chart
    GET  /api/reports               problem reports (reports/ folder, one per stop); GET /api/reports/<id> one;
                                    POST /api/reports-sent/<id>, /api/reports-delete/<id>, /api/reports-clear
    GET  /api/history, POST /api/history-delete/<id>, POST /api/history-clear   jobs that ran (jobs/history.json)
    GET  /api/camera, POST /api/camera, GET /camera.mjpg   camera + person detection
    GET  /api/camera/devices        the cameras Linux can see
    GET  /api/safety                safety controller status
    POST /api/safety/<action>       tick (watchdog + hold-to-run), estop, release, reset, start,
                                    stop, finished, mode, checklist, input, job {name}, clear-job
    GET  /api/situation             plain-English "what's happening" (no AI)
    POST /api/assistant             {question} -> optional AI advisor (advisory only)
    GET  /api/config                settings from config/cell.toml and any problems in them
"""
import argparse
import json
import mimetypes
import os
import re
import socket
import sys
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from beamcell import assistant, collisions, history, machine, manual, nc1, plasma, plasma_presets, reports, sensors, \
    sections as S, uk_codes as UK
from beamcell.config import CONFIG, problems as config_problems
from beamcell.gpio_inputs import GpioInputs
from beamcell.parts import Part, nest_all
from beamcell.planner import Plan
from beamcell.safety import SafetyController
from beamcell.vision import Vision

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
EXAMPLES = os.path.join(ROOT, "examples", "nc1")
JOBS = os.path.join(ROOT, "jobs")
VISION = Vision(os.path.join(ROOT, "models"))
VISION.configure({"zones": {"warning": CONFIG["camera"]["warning_zone"], "danger": CONFIG["camera"]["danger_zone"],
                            "bed": CONFIG["camera"]["bed_zone"]}})
SAFETY = SafetyController(vision=VISION)
GPIO = GpioInputs(SAFETY, CONFIG["gpio"])


def _report_stop(code, text):
    """A stop during a job: save a problem report for the developer (beamcell/reports.py)."""
    st = SAFETY.status()
    cam = VISION.status()
    reports.record(code, text, {
        "job": st.get("job"), "playback": dict(SAFETY.playback),
        "safety": {k: st.get(k) for k in ("state", "mode", "stop_category", "inputs", "input_source", "checklist_ok")} |
                  {"latched": [x["code"] for x in st.get("latched", [])]},
        "events": st.get("events", [])[:40],
        "camera": {"state": "on" if cam["enabled"] else "off", "detector": cam["detector"], "fps": cam["fps"],
                   "people": cam["people"], "in_danger": cam["in_danger"], "message": cam["message"]},
    })


PLANS = {}                                  # plan id -> the bar it was planned for (the bar check at Start needs it)


def _bar_check(job):
    bar = PLANS.get(job.get("plan_id"))
    if bar is None:
        return {"ok": False, "checks": [], "problems": [{"what": "Plan", "text": "this job's plan is no longer on the machine (the app was restarted)",
                                                        "fix": "Press Plan again, then Start."}]}
    return sensors.job_check(bar)


SAFETY.bar_checker = _bar_check
SAFETY.on_stop = _report_stop
SAFETY.on_reset = reports.close_incident


def system_info():
    info = {"python": sys.version.split()[0], "host": socket.gethostname()}
    try:
        with open("/proc/device-tree/model") as fh:
            info["board"] = fh.read().strip("\x00\n")
    except OSError:
        info["board"] = "not a Jetson"
    try:
        mem = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":")
                mem[k] = int(v.split()[0]) // 1024
        info["memory_mb"] = {"total": mem.get("MemTotal"), "available": mem.get("MemAvailable"),
                             "swap_free": mem.get("SwapFree")}
    except OSError:
        pass
    info.update(VISION.capabilities())
    return info


def part_view(part):
    """Everything the browser needs to draw a part."""
    s = part.sec
    outer, holes = S.outline(s)
    return {"part": part.to_dict(), "weight": round(part.weight, 1),
            "section": dict(S.summary(s), outline=outer, holes=holes, plates=S.plates(s)),
            "faces": {f: part.face_outline(f) for f in part.faces()},
            "checks": part.check()}


CAD = os.path.join(ROOT, "cad")


def cad_files():
    """The CAD files in cad/ (made on a PC with python3 -m beamcell.cad) and whether this
    computer can make new part STEP files itself (it needs CadQuery)."""
    out = []
    for dirpath, _, files in os.walk(CAD):
        for f in sorted(files):
            if f.endswith((".step", ".csv")):
                full = os.path.join(dirpath, f)
                out.append({"path": os.path.relpath(full, CAD).replace(os.sep, "/"), "kb": round(os.path.getsize(full) / 1024)})
    from beamcell import cad
    return {"files": sorted(out, key=lambda f: f["path"]), "can_make_parts": cad.cq is not None}


def prototype_info():
    """The 1:10 prototype: the shopping list (with part numbers) and where every position is."""
    import csv
    with open(os.path.join(ROOT, "docs", "prototype_bom.csv")) as fh:
        bom = list(csv.DictReader(fh))
    with open(os.path.join(WEB, "models", "prototype_positions.json")) as fh:
        positions = json.load(fh)
    return {"bom": bom, "positions": positions}


def part_step(body):
    """One part as a STEP solid (text), if CadQuery is installed on this computer."""
    from beamcell import cad
    if cad.cq is None:
        return {"error": "Making STEP files needs CadQuery, which is for a PC (pip install cadquery). Export the "
                         "NC1 file instead and run: python3 -m beamcell.cad parts your_part.nc1"}
    import tempfile
    part = Part.from_dict(body["part"])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "part.step")
        cad.cq.exporters.export(cad.part_solid(part), path)
        with open(path) as fh:
            return {"step": fh.read(), "name": f"{part.mark}.step"}


def parts_from(body):
    return [Part.from_dict(p) for p in body.get("parts", [])]


def plan_bar(body):
    parts = parts_from(body)
    stock = _stock(body)
    bars = nest_all(parts, stock)
    if not bars:
        return {"error": "nothing to cut - add parts (that fit the bar and have no errors)"}
    i = max(0, min(int(body.get("bar", 0)), len(bars) - 1))
    return plan_output(bars[i], body, i, len(bars))


def _stock(body):
    stock = float(body.get("stock_length", UK.DEFAULT_STOCK_M * 1000))
    if stock > machine.WORK_LENGTH * 1000 + 0.5:
        raise ValueError(f"a {stock / 1000:g} m bar doesn't fit the {machine.WORK_LENGTH:g} m machine - pick a shorter stock length")
    return stock


def manual_check(body):
    bar, problems = manual.build(body.get("section", ""), body.get("length", 12000), body.get("cuts", []))
    pieces = [] if bar is None else [
        {"mark": bar.parts[pl["part"]].mark, "x0": pl["x0"], "x1": pl["x1"], "length": round(pl["x1"] - pl["x0"], 1),
         "keep": pl["keep"], "scrap": pl["scrap"], "weight": round(bar.parts[pl["part"]].weight, 1)}
        for pl in bar.placements]
    return {"problems": problems, "pieces": pieces, "ok": bar is not None and not any(p["level"] == "error" for p in problems)}


def manual_plan(body):
    bar, problems = manual.build(body.get("section", ""), body.get("length", 12000), body.get("cuts", []))
    errors = [p for p in problems if p["level"] == "error"]
    if bar is None or errors:
        return {"error": "fix these first: " + "; ".join(f"{p['item']}: {p['text']}" for p in errors), "problems": problems}
    if not body.get("cuts"):
        return {"error": "add at least one cut", "problems": problems}
    out = plan_output(bar, body, 0, 1)
    out["manual"] = True
    out["problems"] = problems
    return out


def safety_decisions():
    """Every stop: what triggers it, the stop category, and what each hand and the operator do."""
    from beamcell.safety import DECISIONS, FAULTS, STOP_CATEGORY
    return [{"code": c, "text": FAULTS[c][0], "ref": FAULTS[c][1],
             "category": STOP_CATEGORY.get(c, 0 if c == "ESTOP" else CONFIG["safety"]["protective_stop_category"]),
             **DECISIONS[c]} for c in FAULTS]


def plan_output(bar, body, i, count):
    t0 = time.time()
    preset, preset_problem = None, None
    if body.get("plasma"):
        try:
            preset = plasma_presets.load(body["plasma"])
        except KeyError as e:
            preset_problem = str(e).strip("'\"") + " - using the cut chart"
    plan = Plan(bar, preset).build()
    if preset_problem:
        plan.warnings.insert(0, preset_problem)
    elif preset and bar.parts and preset.get("section") and preset["section"] != bar.section_title:
        plan.warnings.insert(0, f"plasma settings '{preset['name']}' were saved for {preset['section']}, not {bar.section_title}")
    planned = time.time() - t0
    hits = collisions.check_plan(plan, step=0.4) if body.get("check", True) else []
    out = plan.to_json()
    out.update({
        "bar_index": i, "bar_count": count, "bar": bar.to_dict(),
        "placements": [dict(part_view(bar.parts[pl["part"]]), x0=pl["x0"], x1=pl["x1"]) for pl in bar.placements],
        "stock_section": dict(S.summary(bar.parts[0].sec), outline=S.outline(bar.parts[0].sec)[0],
                              plates=S.plates(bar.parts[0].sec)) if bar.parts else None,
        "collisions": len(hits), "planning_s": round(planned, 2),
        "bar_check": sensors.job_check(bar) if bar.parts else None,      # a preview: it is measured for real at Start
    })
    out["plan_id"] = uuid.uuid4().hex[:12]
    PLANS[out["plan_id"]] = bar
    while len(PLANS) > 30:
        PLANS.pop(next(iter(PLANS)))
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "beamcell/1.0"

    def log_message(self, fmt, *args):            # quiet: only errors
        pass

    # ---------------------------------------------------------------- responses
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=float) if ctype == "application/json"
                                                    else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _static(self, path):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".js"):
            ctype = "text/javascript"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def _cad_file(self, rel):
        full = os.path.normpath(os.path.join(CAD, rel))
        if not full.startswith(CAD + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv" if full.endswith(".csv") else "application/step")
        self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(full)}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------------------------------------------------------------- routes
    def do_GET(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        try:
            if path == "/api/info":
                return self._send(200, {
                    "machine": machine.describe(), "families": S.FAMILY_NAMES, "version": reports.VERSION,
                    "codes": {"bolts": UK.BOLTS, "standard_bolt": UK.STANDARD_BOLT, "hole_types": UK.HOLE_TYPES,
                              "hole_sizes": {b: {k: UK.hole_size(b, k) for k in UK.HOLE_TYPES} for b in UK.BOLTS},
                              "grades": UK.GRADES, "default_grade": UK.DEFAULT_GRADE,
                              "stock_lengths_m": [x for x in UK.STOCK_LENGTHS_M if x <= machine.WORK_LENGTH], "default_stock_m": UK.DEFAULT_STOCK_M,
                              "cope_radius": UK.DEFAULT_COPE_RADIUS, "min_corner_radius": UK.MIN_CORNER_RADIUS},
                    "system": system_info()})
            if path == "/api/sections":
                return self._send(200, {fam: [S.summary(s) for s in rows] for fam, rows in S.library().items()})
            if path == "/api/section":
                s = S.get(parse_qs(url.query)["title"][0])
                outer, holes = S.outline(s)
                return self._send(200, dict(S.summary(s), outline=outer, holes=holes, plates=S.plates(s)))
            if path == "/api/examples":
                return self._send(200, sorted(f for f in os.listdir(EXAMPLES) if f.lower().endswith(".nc1")))
            if path.startswith("/api/examples/"):
                name = os.path.basename(path)
                with open(os.path.join(EXAMPLES, name)) as fh:
                    part, report = nc1.read(fh.read(), name)
                return self._send(200, dict(part_view(part), report=report))
            if path == "/api/history":
                return self._send(200, {"history": history.entries()})
            if path == "/api/jobs":
                os.makedirs(JOBS, exist_ok=True)
                return self._send(200, sorted(f[:-5] for f in os.listdir(JOBS)
                                              if f.endswith(".json") and f.lower() != "history.json"))
            if path.startswith("/api/jobs/"):
                name = _safe_name(os.path.basename(path))
                with open(os.path.join(JOBS, name + ".json")) as fh:
                    return self._send(200, json.load(fh))
            if path == "/api/camera":
                return self._send(200, VISION.status())
            if path == "/api/camera/devices":
                from beamcell.vision import in_video_group, list_cameras
                return self._send(200, {"cameras": list_cameras(), "video_group": in_video_group(),
                                        "opencv": VISION.capabilities()["opencv"]})
            if path == "/api/safety":
                return self._send(200, dict(SAFETY.status(), gpio=GPIO.status()))
            if path == "/api/situation":
                st = SAFETY.status()
                return self._send(200, dict(assistant.situation(st, SAFETY.playback, VISION.status()),
                                            advisor=assistant.available()[0], advisor_why=assistant.available()[1]))
            if path == "/api/config":
                safe = {k: v for k, v in CONFIG.items()}
                return self._send(200, {"config": safe, "problems": config_problems(CONFIG),
                                        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))})
            if path == "/api/sensors":
                return self._send(200, {"sensors": sensors.status(VISION.status()), "groups": sensors.GROUPS,
                                        "decisions": safety_decisions(), "sim_modes": sensors.SIM_MODES,
                                        "sim_bar": sensors.SIM_BAR["mode"]})
            if path == "/api/plasma/presets":
                return self._send(200, {"presets": plasma_presets.entries(), "fields": plasma_presets.ROW,
                                        "ratings": plasma_presets.RATINGS, "grades": plasma_presets.GRADES,
                                        "processes": {k: v["label"] for k, v in plasma.CHARTS.items()},
                                        "current": CONFIG["plasma"]["process"]})
            if path.startswith("/api/plasma/presets/"):
                return self._send(200, plasma_presets.load(path[len("/api/plasma/presets/"):]))
            if path == "/api/plasma/start":
                q = parse_qs(url.query)
                return self._send(200, plasma_presets.start_values(q["section"][0], q.get("process", [CONFIG["plasma"]["process"]])[0],
                                                                   q.get("grade", ["S355"])[0]))
            if path == "/api/reports":
                return self._send(200, {"reports": reports.entries(), "settings": reports.public_settings()})
            if path.startswith("/api/reports/"):
                return self._send(200, reports.load(path[len("/api/reports/"):]))
            if path == "/api/plasma":
                proc = parse_qs(urlparse(self.path).query).get("process", [CONFIG["plasma"]["process"]])[0]
                return self._send(200, dict(plasma.table(proc), processes={k: v["label"] for k, v in plasma.CHARTS.items()},
                                            current=CONFIG["plasma"]["process"]))
            if path == "/api/prototype":
                return self._send(200, prototype_info())
            if path == "/api/cad":
                return self._send(200, cad_files())
            if path.startswith("/cad/"):
                return self._cad_file(path[len("/cad/"):])
            if path == "/camera.mjpg":
                return self._mjpeg()
            if path == "/api/system":
                return self._send(200, system_info())
            return self._static(path)
        except (KeyError, FileNotFoundError) as e:
            return self._send(404, {"error": f"not found: {e}"})
        except Exception as e:                             # noqa: BLE001 - report anything to the browser
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        try:
            body = self._body()
            if path == "/api/nc1":
                part, report = nc1.read(body["text"], body.get("filename", "part.nc1"))
                return self._send(200, dict(part_view(part), report=report))
            if path == "/api/nc1/export":
                return self._send(200, nc1.write(Part.from_dict(body["part"])), "text/plain")
            if path == "/api/part":
                return self._send(200, part_view(Part.from_dict(body["part"])))
            if path == "/api/nest":
                bars = nest_all(parts_from(body), _stock(body))
                return self._send(200, [dict(b.to_dict(), marks=[b.parts[pl["part"]].mark for pl in b.placements])
                                        for b in bars])
            if path == "/api/sensors/simulate-bar":
                if body.get("mode") not in sensors.SIM_MODES:
                    raise ValueError("mode must be one of " + ", ".join(sensors.SIM_MODES))
                sensors.SIM_BAR["mode"] = body["mode"]
                SAFETY.recheck_bar()
                return self._send(200, {"mode": body["mode"]})
            if path == "/api/sensors/measure":
                return self._send(200, sensors.measure_bar(body["section"], float(body.get("length", 12000)), body.get("measured")))
            if path == "/api/machine-size":
                if SAFETY.state == "RUNNING":
                    raise ValueError("stop the machine before changing its size")
                machine.choose_length(body["length_m"])
                SAFETY.clear_job("screen")
                PLANS.clear()
                return self._send(200, {"work_length": machine.WORK_LENGTH})
            if path == "/api/plasma/presets":
                return self._send(200, plasma_presets.save(body))
            if path.startswith("/api/plasma/presets-delete/"):
                plasma_presets.delete(path[len("/api/plasma/presets-delete/"):])
                return self._send(200, {"presets": plasma_presets.entries()})
            if path.startswith("/api/reports-sent/"):
                return self._send(200, reports.mark_sent(path[len("/api/reports-sent/"):]))
            if path.startswith("/api/reports-delete/"):
                reports.delete(path[len("/api/reports-delete/"):])
                return self._send(200, {"reports": reports.entries()})
            if path == "/api/reports-clear":
                reports.clear()
                return self._send(200, {"reports": []})
            if path == "/api/reports/note":
                return self._send(200, reports.add_note(body.get("id", ""), body.get("note", "")))
            if path == "/api/plasma/settings":
                return self._send(200, plasma.settings(body.get("feature", "cut"), float(body["thickness"]),
                                                       body.get("process", CONFIG["plasma"]["process"]), body.get("d")))
            if path == "/api/manual/check":
                return self._send(200, manual_check(body))
            if path == "/api/manual/plan":
                return self._send(200, manual_plan(body))
            if path == "/api/cad/part":
                return self._send(200, part_step(body))
            if path == "/api/plan":
                return self._send(200, plan_bar(body))
            if path.startswith("/api/history-delete/"):
                history.delete(os.path.basename(path))
                return self._send(200, {"history": history.entries()})
            if path == "/api/history-clear":
                history.clear()
                return self._send(200, {"history": []})
            if path.startswith("/api/jobs-delete/"):
                name = _safe_name(os.path.basename(path))
                os.remove(os.path.join(JOBS, name + ".json"))
                return self._send(200, {"deleted": name})
            if path.startswith("/api/jobs/"):
                name = _safe_name(os.path.basename(path))
                os.makedirs(JOBS, exist_ok=True)
                with open(os.path.join(JOBS, name + ".json"), "w") as fh:
                    json.dump(body, fh, indent=1)
                return self._send(200, {"saved": name})
            if path == "/api/camera":
                return self._send(200, VISION.configure(body))
            if path.startswith("/api/safety/"):
                return self._safety(path.rsplit("/", 1)[1], body)
            if path == "/api/assistant":
                facts = {"safety": SAFETY.status(), "playback": SAFETY.playback, "camera": VISION.status()}
                facts["safety"].pop("events", None)
                facts["situation"] = assistant.situation(SAFETY.status(), SAFETY.playback, VISION.status())["text"]
                return self._send(200, assistant.ask(body.get("question", ""), facts, VISION.jpeg()))
            return self._send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:                             # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def _safety(self, action, body):
        who = body.get("who", "screen")
        if action == "tick":
            return self._send(200, SAFETY.tick(body.get("client", "screen"), bool(body.get("enable")), body.get("playback")))
        if action == "estop":
            SAFETY.press_estop(body.get("source", "screen"))
        elif action == "release":
            SAFETY.release_estop(body.get("source", "screen"))
        elif action in ("reset", "start"):
            ok, why = (SAFETY.reset if action == "reset" else SAFETY.start)(who)
            return self._send(200, dict(SAFETY.status(), ok=ok, why=why))
        elif action == "stop":
            SAFETY.stop(who, body.get("reason", "stop button"))
        elif action == "finished":
            job = SAFETY.job and dict(SAFETY.job)
            SAFETY.finished()
            if job and job["state"] != "finished":                # once per job, not on every repeat
                history.add(job, "finished", body.get("details"))
        elif action in ("job", "clear-job"):
            job = SAFETY.job and dict(SAFETY.job)
            ok, why = SAFETY.load_job(body.get("name", "job"), who, body.get("plan_id")) if action == "job" else SAFETY.clear_job(who)
            if ok and action == "clear-job" and job and job["started"] and job["state"] != "finished":
                history.add(job, "cleared before the end", body.get("details"))
            return self._send(200, dict(SAFETY.status(), ok=ok, why=why))
        elif action == "mode":
            SAFETY.set_mode(body["mode"], bool(body.get("lockout_confirmed")))
        elif action == "checklist":
            SAFETY.confirm_checklist(who)
        elif action == "input":
            SAFETY.set_input(body["name"], bool(body["value"]))
        else:
            return self._send(404, {"error": f"unknown safety action {action}"})
        return self._send(200, dict(SAFETY.status(), ok=True, why=[]))

    def _mjpeg(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = None
        try:
            while True:
                frame = VISION.jpeg()
                if frame is not None and frame is not last:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                    last = frame
                time.sleep(0.08)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _safe_name(name):
    name = re.sub(r"[^A-Za-z0-9_. -]", "", name).strip(". ")
    if not name:
        raise ValueError("bad name")
    if name.lower() == "history":                   # jobs/history.json is the job history, not a saved job
        raise ValueError("'history' is kept for the job history - choose another name")
    return name


def lan_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "localhost"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Beam cutting cell - web app")
    ap.add_argument("--port", type=int, default=CONFIG["server"]["port"])
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = other computers on the network can open it")
    ap.add_argument("--camera", default=None, help="camera to start with: auto, 0 / 1 (USB), 'csi', or a video file")
    args = ap.parse_args(argv)
    for p in config_problems(CONFIG):
        print("CONFIG PROBLEM:", p)
    SAFETY.watchdog()
    GPIO.start()
    if GPIO.error:
        print("GPIO:", GPIO.error)
    camera = args.camera if args.camera is not None else (CONFIG["camera"]["source"] if CONFIG["camera"]["autostart"] else None)
    if camera is not None:
        print(VISION.configure({"enabled": True, "source": camera, "model": CONFIG["camera"]["model"]}).get("message", ""))
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        if e.errno not in (98, 48):                     # 98 Linux / 48 macOS: address already in use
            raise
        print(f"\nCAN'T START: port {args.port} is already in use - Beam Cell (an older copy?) is already running.\n"
              "Stop it first, then run ./start.sh again:\n"
              "  - started at boot:        sudo systemctl restart beamcell   (this restarts it with the new version)\n"
              "  - in another terminal:    press Ctrl+C there\n"
              f"  - not sure:               pkill -f beamcell.server   (stops every copy)\n"
              f"Or use another port:       ./start.sh --port {args.port + 1}")
        sys.exit(1)
    print(f"Beam Cell version {reports.VERSION}")
    print(f"Beam cutting cell running:\n  on this computer:   http://localhost:{args.port}\n"
          f"  from the network:   http://{lan_address()}:{args.port}\nPress Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        VISION.configure({"enabled": False})
        httpd.server_close()


if __name__ == "__main__":
    main()
