"""
Problem reports: when the machine stops during a job, everything the developer needs to find out
why is saved in one file in reports/ (kept on the machine, not in git):

    {"id", "time", "stops": [{"time", "code", "text"}], "job", "safety": {state, mode, inputs, latched},
     "events": [the last safety events], "playback", "camera", "plasma", "version", "system",
     "note": what the operator adds, "sent": "" | how and when it went to the developer}

Stops that follow each other before a Reset (an E-stop, then the screen losing contact, ...) are one
incident, so they go into the same report.

Sending it to the developer ([reports] in config/cell.toml):
  - the Reports window opens it as a new GitHub issue (github_repo), ready to submit, or
  - with webhook_url set, each report is also POSTed there as JSON the moment it is made
    (e.g. a Slack / Teams / Discord incoming webhook, or your own server).
"""
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import urllib.request

from beamcell.config import CONFIG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(ROOT, "reports")
_lock = threading.Lock()
_open = {"id": None}                    # the incident still open (no Reset since)


def settings():
    return CONFIG.get("reports", {})


def public_settings():
    s = settings()
    return {"github_repo": s.get("github_repo", ""), "webhook": bool(s.get("webhook_url"))}


def _version():
    try:
        out = subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%h %cd", "--date=short"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _system():
    model = ""
    try:
        with open("/proc/device-tree/model") as fh:
            model = fh.read().strip("\x00\n ")
    except OSError:
        pass
    return {"computer": model or platform.node(), "os": platform.platform(), "python": sys.version.split()[0]}


VERSION = _version()
SYSTEM = _system()


def _path(rid, folder):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[A-Z_]+(-[0-9]+)?", rid or ""):
        raise KeyError(f"no report {rid!r}")
    return os.path.join(folder, rid + ".json")


def _write(r, folder):
    os.makedirs(folder, exist_ok=True)
    path = _path(r["id"], folder)
    with open(path + ".tmp", "w") as fh:
        json.dump(r, fh, indent=1, default=str)
    os.replace(path + ".tmp", path)


def _read(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def record(code, text, context, folder=None):
    """A stop during a job: start a report, or add to the one still open. Returns the report."""
    folder = folder or FOLDER
    now = time.time()
    stop = {"time": time.strftime("%H:%M:%S", time.localtime(now)), "code": code, "text": text}
    with _lock:
        r = _read(_path(_open["id"], folder)) if _open["id"] else None
        if r is None:
            base = rid = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + code
            n = 1
            while os.path.exists(os.path.join(folder, rid + ".json")):
                n += 1
                rid = f"{base}-{n}"
            r = {"id": rid, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "stops": [],
                 "note": "", "sent": "", "version": VERSION, "system": SYSTEM}
            _open["id"] = rid
        r["stops"].append(stop)
        r["title"] = r["stops"][0]["text"] + (f" (+{len(r['stops']) - 1} more)" if len(r["stops"]) > 1 else "")
        r.update(context)                                  # latest safety state, events, job, camera, playback
        _write(r, folder)
        _trim(folder)
    if len(r["stops"]) == 1 and settings().get("webhook_url"):
        threading.Thread(target=_send_webhook, args=(r["id"], folder), daemon=True).start()
    return r


def close_incident():
    """Reset: the next stop starts a new report."""
    with _lock:
        _open["id"] = None


def _send_webhook(rid, folder):
    time.sleep(3)                                      # let the stops that follow join the report first
    url = settings().get("webhook_url")
    try:
        r = load(rid, folder)
        text = f"BEAM CELL stopped: {r['title']}\n{summary(r)}"
        body = json.dumps({"text": text, "content": text[:1900], "report": r}, default=str).encode()
        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            pass
        mark_sent(rid, "webhook", folder)
    except Exception as e:                             # noqa: BLE001 - no network: it stays unsent, shown on screen
        with _lock:
            r = _read(_path(rid, folder))
            if r:
                r["send_error"] = f"webhook failed: {e}"[:200]
                _write(r, folder)


def summary(r):
    """The report as plain text - what goes into the GitHub issue or the message."""
    lines = [f"When: {r['time']}", f"Software: {r.get('version', '?')}", f"Computer: {r.get('system', {}).get('computer', '?')}"]
    job = r.get("job") or {}
    if job:
        lines.append(f"Job: {job.get('name', '')} (run {job.get('runs', 0)})")
    pb = r.get("playback") or {}
    if pb.get("bar"):
        lines.append(f"Cutting: {pb['bar']}, {pb.get('t', 0)} s in ({pb.get('progress', 0):.0f}%)")
        lines.append(f"  Cutter: {pb.get('cutter', '')}")
        lines.append(f"  Handler: {pb.get('handler', '')}")
    if pb.get("plasma"):
        lines.append(f"Plasma settings: {pb['plasma']}")
    lines.append("")
    lines.append("Stops:")
    lines += [f"  {s['time']}  {s['text']}" for s in r["stops"]]
    sf = r.get("safety") or {}
    if sf:
        lines.append("")
        lines.append(f"Safety: state {sf.get('state')}, mode {sf.get('mode')}, latched {', '.join(sf.get('latched', [])) or 'none'}")
        off = [k for k, v in (sf.get("inputs") or {}).items() if not v]
        lines.append("Inputs not OK: " + (", ".join(off) or "none"))
    cam = r.get("camera") or {}
    if cam:
        lines.append("Camera: " + (f"on, {cam.get('detector') or 'no detector'}, {cam.get('fps', 0)} pictures/s, "
                                   f"{cam.get('people', 0)} people seen" if cam.get("state") == "on" else "off"))
    if r.get("note"):
        lines += ["", "Operator's note:", r["note"]]
    lines += ["", "Last safety events:"]
    lines += [f"  {e.get('time', '')}  {e.get('text', '')}" for e in (r.get("events") or [])[:25]]
    return "\n".join(lines)


def _trim(folder):
    keep = int(settings().get("keep", 200))
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
    for f in files[:-keep] if len(files) > keep else []:
        os.remove(os.path.join(folder, f))


def load(rid, folder=None):
    r = _read(_path(rid, folder or FOLDER))
    if r is None:
        raise KeyError(f"no report {rid!r}")
    r["text"] = summary(r)
    return r


def entries(folder=None):
    folder = folder or FOLDER
    if not os.path.isdir(folder):
        return []
    out = []
    for f in sorted(os.listdir(folder), reverse=True):
        if f.endswith(".json"):
            r = _read(os.path.join(folder, f))
            if r:
                out.append({"id": r["id"], "time": r["time"], "title": r.get("title", ""), "stops": len(r.get("stops", [])),
                            "job": (r.get("job") or {}).get("name", ""), "sent": r.get("sent", ""),
                            "send_error": r.get("send_error", ""), "note": r.get("note", "")})
    return out


def _change(rid, folder, **kw):
    folder = folder or FOLDER
    with _lock:
        r = _read(_path(rid, folder))
        if r is None:
            raise KeyError(f"no report {rid!r}")
        r.update(kw)
        _write(r, folder)
    return load(rid, folder)


def mark_sent(rid, how="GitHub issue", folder=None):
    return _change(rid, folder, sent=f"{how}, {time.strftime('%Y-%m-%d %H:%M')}", send_error="")


def add_note(rid, note, folder=None):
    return _change(rid, folder, note=str(note)[:2000])


def delete(rid, folder=None):
    path = _path(rid, folder or FOLDER)
    if not os.path.exists(path):
        raise KeyError(f"no report {rid!r}")
    os.remove(path)


def clear(folder=None):
    folder = folder or FOLDER
    with _lock:
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if f.endswith(".json"):
                    os.remove(os.path.join(folder, f))
        _open["id"] = None
