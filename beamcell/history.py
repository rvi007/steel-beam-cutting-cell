"""
Job history: every job that ran, kept in jobs/history.json (newest first) so the operator can see
what was cut and when, and delete old entries.

    {"id", "name", "section", "what", "parts", "duration_s", "result": "finished" | "cleared",
     "runs", "loaded", "ended", "problems": [{"time", "text"}]}

"problems" lists every stop while the job was under way (E-stop, gate, camera, load slipping, the
Stop button...): an empty list means it ran clean.
"""
import json
import os
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "jobs", "history.json")
MAX = 500                                   # oldest entries drop off after this many
_lock = threading.Lock()


def _load(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(entries, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(entries[:MAX], fh, indent=1)
    os.replace(tmp, path)


def entries(path=PATH):
    with _lock:
        return _load(path)


def add(job, result, details=None, path=PATH):
    """Record a job from the safety controller (its name, runs) plus what the screen knows about it."""
    d = details or {}
    e = {"id": uuid.uuid4().hex[:12], "name": job.get("name", "job"), "result": result,
         "runs": job.get("runs", 0),
         "loaded": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job["loaded_at"])) if job.get("loaded_at") else "",
         "ended": time.strftime("%Y-%m-%d %H:%M:%S"),
         "section": str(d.get("section", ""))[:60], "what": str(d.get("what", ""))[:200],
         "parts": int(d.get("parts", 0) or 0), "duration_s": round(float(d.get("duration_s", 0) or 0), 1),
         "problems": [dict(p) for p in job.get("problems", [])]}
    with _lock:
        items = _load(path)
        items.insert(0, e)
        _save(items, path)
    return e


def delete(entry_id, path=PATH):
    with _lock:
        items = _load(path)
        keep = [e for e in items if e.get("id") != entry_id]
        if len(keep) == len(items):
            raise KeyError(entry_id)
        _save(keep, path)


def clear(path=PATH):
    with _lock:
        _save([], path)
