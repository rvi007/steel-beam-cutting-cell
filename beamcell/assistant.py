"""
"What's happening?" - two levels:

1. situation()  ALWAYS ON, no AI. Builds plain-English sentences from the facts the cell
   already knows: safety state, what each hand is doing, which part / section / face,
   who the camera sees. Deterministic and instant - this is what the screen shows.

2. ask()        OPTIONAL Claude advisor ([assistant] in config/cell.toml). The operator asks
   a question ("why did it stop?", "is this notch OK for a UB 457?", "what's on the camera?")
   and Claude answers from the same facts plus, if allowed, the latest camera picture.
   It is ADVISORY ONLY: it has no way to move, start or reset the machine, and it is never
   part of the safety system (an AI model is not safety-rated). Needs internet,
   `pip install anthropic` and an API key - see docs/ASSISTANT.md.
"""
import base64
import json

from beamcell.config import CONFIG

try:
    import anthropic
except ImportError:                     # the cell works fine without it
    anthropic = None

SYSTEM = """You are the operator's advisor for a prototype 12 m structural steel beam cutting cell in the UK.
Two overhead robot hands share a gantry: the Cutter (plasma torch) cuts holes, notches and parts to length;
the Handler (magnet) holds parts while they are cut free and puts them on the outfeed table.
Sections are UK (BS 4-1, BS EN 10056-1); fabrication rules are BS EN 1090-2 and BS EN 1993-1-8 with the UK NA;
workplace law is PUWER 1998, LOLER 1998, COSHH 2002, and machinery standards BS EN ISO 12100, 13849-1, 13850,
60204-1, 10218.

You are given the cell's live facts as JSON (and sometimes a camera picture). Answer the operator's question
briefly in plain English (short sentences, no jargon without explaining it). Base every statement on the facts
or the picture; say plainly when you can't tell.

You cannot control the machine. Never tell anyone to bypass, override, defeat or mute a stop, guard, interlock,
light curtain or E-stop, or to enter the cell while it can move. If something looks unsafe, say to press the
E-stop and tell the supervisor. Stops are reset only by a trained person after finding the cause."""


def situation(safety, playback=None, camera=None):
    """Plain-English summary of the cell right now, from facts only."""
    playback = playback or {}
    camera = camera or {}
    lines = []
    st = safety["state"]
    mode = {"AUTO": "Auto", "MANUAL": "Manual (reduced speed, hold-to-run)", "MAINTENANCE": "Maintenance"}[safety["mode"]]
    if st == "ESTOP":
        lines.append("EMERGENCY STOP. " + ("The E-stop is still pressed (" + ", ".join(safety["estop_sources"]) + ")."
                                           if safety["estop_pressed"] else "The E-stop has been released - press Reset."))
    elif st == "FAULT":
        lines.append("STOPPED: " + "; ".join(f["text"] for f in safety["latched"]) + ".")
    elif st == "ISOLATED":
        lines.append("Isolated for maintenance (locked off). Nothing can move.")
    elif st == "NOT_RESET":
        lines.append("Waiting for Reset.")
    elif st == "READY":
        job = safety.get("job")
        if job and job["state"] == "finished":
            lines.append(f"Job '{job['name']}' finished. Clear the outfeed table and scrap tray, then clear the job "
                         "or load the next one - the next run needs the checklist again.")
        elif not job:
            lines.append("Reset done - plan a job on the Machine tab.")
        else:
            lines.append(f"Reset done - ready to start '{job['name']}'." +
                         ("" if safety["checklist_ok"] else " Confirm the pre-start checklist for this job first."))
    elif st == "PAUSED":
        lines.append("Paused - press Start to carry on.")
    elif st == "RUNNING":
        speed = safety["speed_factor"]
        if safety["mode"] == "MANUAL" and not safety["enable_held"]:
            lines.append("Manual mode: hold the enable button to move.")
        else:
            lines.append(f"Running in {mode}" + (f" at {speed * 100:.0f}% speed" if speed < 1 else "") + ".")
    if safety["reset_blockers"] and st in ("ESTOP", "FAULT", "NOT_RESET"):
        lines.append("Before Reset: " + "; ".join(safety["reset_blockers"]) + ".")
    if playback.get("cutter"):
        lines.append(f"Cutter: {playback['cutter']}.")
    if playback.get("handler") and playback.get("handler") != "waiting":
        lines.append(f"Handler: {playback['handler']}.")
    if playback.get("bar"):
        lines.append(f"Bar: {playback['bar']}" + (f", {playback.get('progress', 0):.0f}% done." if "progress" in playback else "."))
    if camera.get("enabled"):
        n = camera.get("people", 0)
        where = " in the DANGER zone" if camera.get("in_danger") else " in the warning zone" if camera.get("in_warning") else ""
        lines.append(f"Camera: {n} person{'s' if n != 1 else ''} seen{where}." if n else "Camera: nobody in view.")
    if not safety["inputs"]["extraction_on"]:
        lines.append("Fume extraction is OFF - no cutting allowed.")
    if not safety["inputs"]["gate_closed"]:
        lines.append("The gate is open.")
    return {"text": " ".join(lines), "lines": lines}


def available():
    cfg = CONFIG["assistant"]
    if not cfg["enabled"]:
        return False, "The advisor is switched off ([assistant] enabled = false in config/cell.toml)."
    if anthropic is None:
        return False, "The advisor needs the Anthropic SDK: pip install anthropic (see docs/ASSISTANT.md)."
    return True, ""


def ask(question, facts, jpeg=None, client=None):
    """Ask Claude about the cell. Returns {"answer"} or {"error"}. Advisory only."""
    ok, why = available()
    if not ok and client is None:
        return {"error": why}
    cfg = CONFIG["assistant"]
    content = []
    if jpeg and cfg["send_camera"]:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(jpeg).decode("ascii")}})
    content.append({"type": "text", "text": "Live facts from the cell (JSON):\n" + json.dumps(facts, default=str)[:20000]
                    + "\n\nOperator's question: " + question.strip()[:2000]})
    try:
        client = client or anthropic.Anthropic(timeout=60.0)
        response = client.beta.messages.create(
            model=cfg["model"],
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": cfg["effort"]},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except Exception as e:                       # noqa: BLE001 - see the typed chain below
        return {"error": _explain(e)}
    if response.stop_reason == "refusal":
        return {"error": "The advisor declined to answer that question."}
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return {"answer": text or "(no answer)", "model": response.model}


def _explain(e):
    """Most specific first, so the operator gets a useful message."""
    if anthropic is None:
        return str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return "No valid API key - set ANTHROPIC_API_KEY (see docs/ASSISTANT.md)."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "The API key isn't allowed to use this model."
    if isinstance(e, anthropic.NotFoundError):
        return f"Model '{CONFIG['assistant']['model']}' not found - check [assistant] model in config/cell.toml."
    if isinstance(e, anthropic.RateLimitError):
        return "Too many questions at once - wait a minute and ask again."
    if isinstance(e, anthropic.BadRequestError):
        return f"The request was rejected: {e.message}"
    if isinstance(e, anthropic.APIStatusError):
        return f"The service had a problem ({e.status_code}) - try again shortly."
    if isinstance(e, anthropic.APIConnectionError):
        return "No internet connection to the advisor - the cell itself is unaffected."
    return f"Advisor error: {e}"
