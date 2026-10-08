"""
Carrying on after an interruption: a stop, a closed browser, a crash or a POWER CUT.

While a job is under way the machine writes where it is to jobs/recovery.json, at most once a
second and at once on every stop (the file is replaced in one step, so a power cut never leaves
half a file):

    {"job": {name, request (what to plan it again from), runs, ...},
     "t": seconds into the plan, "op": the operation under way, "done": operations finished,
     "total": operations in the plan, "cutter"/"handler": what each hand was doing,
     "state": safety state, "saved": when, "last_stop": the stop that interrupted it (if any)}

When the app starts again it offers to carry on: it plans the job again from the same request
(the plan is repeatable), goes back to the START of the operation that was interrupted - a cut
half done is cut again from its start - and, before anything moves, measures the bar again and
checks with the torch camera that everything already cut is where the program says.
The file is deleted when the job finishes or is cleared.
"""
import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "jobs", "recovery.json")
_lock = threading.Lock()
_last = {"t": 0.0}


def save(job, playback, safety_state, last_stop=None, force=False, path=None):
    """Write the progress of a job that is under way (throttled to once a second unless force)."""
    path = path or PATH
    if not job or not job.get("started") or job.get("state") == "finished" or not job.get("request"):
        return False
    now = time.time()
    if not force and now - _last["t"] < 1.0:
        return False
    _last["t"] = now
    pb = playback or {}
    old = load(path) or {}
    data = {"job": {k: job.get(k) for k in ("name", "request", "runs", "loaded_at", "plan_id")},
            "t": pb.get("t_exact", pb.get("t", 0)), "op": pb.get("op", ""), "done": pb.get("done", 0), "total": pb.get("total", 0),
            "cutter": pb.get("cutter", ""), "handler": pb.get("handler", ""), "bar": pb.get("bar", ""),
            "state": safety_state, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_stop": last_stop or (old.get("last_stop") if old.get("job", {}).get("name") == job.get("name") else None)}
    if old.get("job", {}).get("name") == job.get("name") and data["t"] < old.get("t", 0) and not force:
        data["t"], data["op"], data["done"] = old["t"], old.get("op", ""), old.get("done", 0)   # never go backwards
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as fh:
            json.dump(data, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())                      # on the disk before we say it is saved
        os.replace(path + ".tmp", path)
    return True


def load(path=None):
    try:
        with open(path or PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def summary(path=None):
    """What the screen shows: the saved progress and why it stopped, in plain words."""
    r = load(path)
    if not r:
        return None
    why = r.get("last_stop") or ("The power went off, the app was closed or the screen lost contact while it was running"
                                 if r.get("state") == "RUNNING" else "The machine was stopped or paused")
    r["why"] = why
    return r


def clear(path=None):
    with _lock:
        try:
            os.remove(path or PATH)
        except OSError:
            pass
