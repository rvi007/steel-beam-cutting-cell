"""
The safety controller: the one place that decides whether the machine may move.

It copies how a real machine's safety circuit behaves (BS EN ISO 13849-1, BS EN 60204-1,
BS EN ISO 13850, BS EN ISO 10218) so the prototype can be operated, tested and demonstrated
the right way. IT IS NOT A SAFETY DEVICE: the Jetson, Python and the browser are not
safety-rated. A real machine needs the same functions in hard-wired safety hardware
(safety relay or safety PLC) - see docs/SAFETY.md.

States
    ISOLATED   Maintenance mode: power isolated, locked off (Lock Out Tag Out). Nothing moves.
    ESTOP      Emergency stop latched. Release the button, then Reset.
    FAULT      Protective stop latched (gate, light curtain, person, camera, watchdog...). Reset.
    NOT_RESET  Power-on or after maintenance: press Reset before anything can start.
    READY      Reset done, waiting for Start.
    PAUSED     Normal stop (category 2) - Start continues.
    RUNNING    The machine may move.

Rules that make it behave like a real safety system:
    - Every stop LATCHES. Clearing the cause (releasing the E-stop, closing the gate) never
      restarts the machine by itself: Reset must be pressed, and only works when every cause
      is gone. Start is a separate, deliberate action (BS EN 60204-1, BS EN ISO 13850).
    - Start needs the pre-start checklist confirmed.
    - Manual mode: reduced speed (250 mm/s max) and hold-to-run - motion only while the
      enable button is held (BS EN ISO 10218-1).
    - Watchdogs: if the operator screen or a required camera goes quiet, the machine stops.
    - Fume extraction off: no plasma (COSHH).
    - Every event goes to an audit log with a time stamp.
"""
import json
import os
import threading
import time
from collections import deque

from beamcell.config import CONFIG, ROOT

AUTO, MANUAL, MAINTENANCE = "AUTO", "MANUAL", "MAINTENANCE"
GANTRY_MAX_MM_S = 1000.0          # fastest axis of the machine (bridge travel)

FAULTS = {
    "ESTOP": ("Emergency stop pressed", "BS EN ISO 13850, PUWER reg 16"),
    "GATE": ("Gate opened in Auto mode", "BS EN ISO 14119, PUWER reg 11"),
    "CURTAIN": ("Light curtain broken in Auto mode", "BS EN IEC 61496-2, BS EN ISO 13855"),
    "PERSON": ("Camera saw a person in the danger zone", "extra protection - not a safety-rated function"),
    "CAMERA": ("Camera stopped working (the settings require it)", "config: safety.require_camera"),
    "HEARTBEAT": ("Operator screen stopped responding", "watchdog"),
    "EXTRACTION": ("Fume extraction stopped while cutting", "COSHH 2002 - local exhaust ventilation"),
    "GPIO": ("Safety input wiring or GPIO fault", "fail-safe: a broken wire counts as a stop"),
    "OBJECT": ("Something is on the bed in the hands' path", "PUWER reg 11 - camera 1 object detection (advisory)"),
    "LOAD": ("The Handler's load is slipping or not what it should be", "LOLER, BS EN 13155 - magnet current / load cell"),
    "TORCH": ("Torch collision - breakaway switch opened", "BS EN ISO 17916 - safety of thermal cutting machines"),
    "FIRE": ("Flame or smoke detected in the cell", "Regulatory Reform (Fire Safety) Order 2005, BS EN ISO 17916"),
}

# Stop category for each stop when the machine was running (BS EN 60204-1). A category 2 stop keeps
# the drives powered, so the hands hold their position and the magnet keeps its grip.
STOP_CATEGORY = {"OBJECT": 2, "LOAD": 2}

# What each hand does, and what the operator must do, for every stop. These are fixed rules, decided
# in advance and checked in the risk assessment - never left to an AI to decide on the spot.
DECISIONS = {
    "ESTOP": {"cutter": "Torch off at once; stops dead (power cut).",
              "handler": "Stops dead. The magnet stays ON (battery backup) - it never drops a part on a stop.",
              "you": "Find out why, make it safe, release the E-stop, press Reset, then Start."},
    "GATE": {"cutter": "Torch off; controlled stop.", "handler": "Stops; keeps holding its part.",
             "you": "Leave the cell, close the gate, press Reset, then Start."},
    "CURTAIN": {"cutter": "Torch off; controlled stop.", "handler": "Stops; keeps holding its part.",
                "you": "Step back out of the light curtain, press Reset, then Start."},
    "PERSON": {"cutter": "Torch off; controlled stop.", "handler": "Stops; keeps holding its part - never lowers a load towards a person.",
               "you": "Everyone out of the danger zone, then Reset and Start."},
    "CAMERA": {"cutter": "Torch off; controlled stop.", "handler": "Stops; keeps holding its part.",
               "you": "Get the camera working again (Camera tab, python3 -m beamcell.doctor), then Reset."},
    "HEARTBEAT": {"cutter": "Torch off; controlled stop.", "handler": "Stops; keeps holding its part.",
                  "you": "Reload the operator screen, check the network, then Reset."},
    "EXTRACTION": {"cutter": "Torch off at once (no plasma without extraction); stops.", "handler": "Stops; keeps holding its part.",
                   "you": "Get the extraction running and drawing air, then Reset."},
    "GPIO": {"cutter": "Torch off; stops.", "handler": "Stops; keeps holding its part.",
             "you": "Check the safety input wiring (a broken wire counts as a stop), then Reset."},
    "OBJECT": {"cutter": "Torch off; holds where it is (category 2 stop) - won't move into the area with the object.",
               "handler": "Holds where it is; won't set a part down on the object.",
               "you": "Open the gate (the machine is stopped), take the object off the bed, close the gate, Reset, Start."},
    "LOAD": {"cutter": "Torch off; stops and moves no further.",
             "handler": "Stops moving sideways at once. Magnet stays ON. If the floor and bed under the part are clear, "
                        "lowers it slowly straight down onto the bed or outfeed table; if not, holds it and sounds the alarm.",
             "you": "Keep everyone out from under the load. When the part is down, check the magnet, the part's weight "
                    "and that it was cut free, then Reset."},
    "TORCH": {"cutter": "Torch off at once; stops; then lifts straight up 50 mm.",
              "handler": "Stops; keeps holding its part.",
              "you": "Check the torch, nozzle and cable; re-seat the breakaway mount; re-measure the bar; Reset."},
    "FIRE": {"cutter": "Torch off at once; stops and lifts clear.", "handler": "Stops; keeps holding its part.",
             "you": "Fire alarm: follow the fire procedure. The extraction keeps running. Reset only when the fire is out "
                    "and the scrap tray checked."},
}

# inputs from the screen (simulated) or from real sensors: name -> (normal text, stop text)
INPUT_WORDS = {"gate_closed": ("gate closed", "GATE OPENED"), "curtain_clear": ("light curtain clear", "LIGHT CURTAIN BROKEN"),
               "extraction_on": ("fume extraction on", "fume extraction OFF"),
               "bed_clear": ("bed clear", "OBJECT ON THE BED (camera 1)"),
               "load_secure": ("Handler load secure", "HANDLER LOAD SLIPPING (magnet current / load cell)"),
               "torch_ok": ("torch mount OK", "TORCH COLLISION (breakaway switch)"),
               "no_fire": ("no flame / smoke", "FLAME / SMOKE DETECTED")}


class SafetyController:
    def __init__(self, vision=None, config=None, log_path=None):
        self.cfg = config or CONFIG["safety"]
        self.vision = vision
        self.lock = threading.RLock()
        self.mode = AUTO
        self.state = "NOT_RESET"
        self.latched = {}                       # code -> time latched
        self.stop_category = None
        self.estop_sources = set()              # who is holding the E-stop down
        self.inputs = {k: True for k in INPUT_WORDS}
        self.input_source = {k: "simulated" for k in INPUT_WORDS}
        self.checklist_ok = False
        self.checklist_for = None               # the job the checklist was confirmed for (None: the next job)
        self.job = None                         # {"name", "state": loaded|running|finished, "started", "runs"}
        self.gpio_ok = True
        self.enable_until = 0.0                 # hold-to-run: enable valid until this time
        self.last_beat = None
        self.playback = {}
        self.events = deque(maxlen=200)
        path = log_path if log_path is not None else self.cfg.get("log_file", "")
        self.log_path = os.path.join(ROOT, path) if path and not os.path.isabs(path) else path
        self._event("power on - press Reset to start")

    # ---------------------------------------------------------------- logging
    def _event(self, text, kind="info"):
        e = {"t": time.time(), "time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "text": text,
             "mode": self.mode, "state": self.state}
        self.events.appendleft(e)
        if self.log_path:
            try:
                os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                with open(self.log_path, "a") as fh:
                    fh.write(json.dumps(e) + "\n")
            except OSError:
                pass

    # ---------------------------------------------------------------- inputs
    def press_estop(self, source="panel"):
        with self.lock:
            new = not self.estop_sources
            self.estop_sources.add(source)
            if new or "ESTOP" not in self.latched:
                self._latch("ESTOP", f"E-STOP pressed ({source})")

    def release_estop(self, source="panel"):
        with self.lock:
            if source in self.estop_sources:
                self.estop_sources.discard(source)
                self._event(f"E-stop released ({source}) - press Reset")

    def set_input(self, name, value, source="simulated"):
        """gate_closed, curtain_clear, extraction_on (from the screen in simulation, or from GPIO)."""
        with self.lock:
            if name not in self.inputs:
                raise ValueError(f"unknown input {name}")
            if self.input_source[name] == "gpio" and source != "gpio":
                raise ValueError(f"{name} comes from the real switch (GPIO) - it can't be changed from the screen")
            self.input_source[name] = source
            if self.inputs[name] != bool(value):
                self.inputs[name] = bool(value)
                words = INPUT_WORDS[name]
                self._event(words[0] if value else words[1], "info" if value else "warn")
            self._evaluate()

    def gpio_fault(self, text):
        with self.lock:
            self.gpio_ok = False
            self._latch("GPIO", text)

    def gpio_restored(self):
        with self.lock:
            if not self.gpio_ok:
                self.gpio_ok = True
                self._event("safety inputs working again - press Reset")

    def confirm_checklist(self, who="operator"):
        with self.lock:
            self.checklist_ok = True
            self.checklist_for = self.job["name"] if self.job else None
            self._event(f"pre-start checklist confirmed by {who}" + (f" for job '{self.job['name']}'" if self.job else ""))

    # ---------------------------------------------------------------- jobs: every job gets its own checklist
    def load_job(self, name, who="screen"):
        """A job (a planned bar, or manual cuts) is loaded. The checklist done for an earlier job that
        ran doesn't count: the cell has changed (parts on the table, scrap in the tray)."""
        with self.lock:
            if self.state == "RUNNING":
                return False, ["stop the machine before loading another job"]
            name = str(name)[:120] or "job"
            prev = self.job
            same = prev is not None and prev["name"] == name and prev["state"] != "finished"
            if not same:
                if self.checklist_ok and prev and prev["started"]:     # the last job ran: walk round again
                    self.checklist_ok = False
                    self.checklist_for = None
                self.job = {"name": name, "state": "loaded", "started": False, "runs": 0, "loaded_at": time.time()}
                if self.checklist_ok:                       # nothing has run since it was confirmed: it carries over
                    self.checklist_for = name
                self._event(f"job loaded: '{name}'" + ("" if self.checklist_ok else " - confirm the pre-start checklist for it"))
            return True, []

    def clear_job(self, who="screen"):
        """The operator deletes the current job."""
        with self.lock:
            if self.state == "RUNNING":
                return False, ["stop the machine before clearing the job"]
            if self.job:
                self._event(f"job cleared by {who}: '{self.job['name']}'")
                if self.job["started"]:
                    self.checklist_ok = False
                    self.checklist_for = None
            self.job = None
            return True, []

    # ---------------------------------------------------------------- commands
    def set_mode(self, mode, lockout_confirmed=False):
        with self.lock:
            if mode not in (AUTO, MANUAL, MAINTENANCE):
                raise ValueError("mode must be AUTO, MANUAL or MAINTENANCE")
            if mode == self.mode:
                return self.status()
            if mode == MAINTENANCE and not lockout_confirmed:
                raise ValueError("Maintenance: isolate the machine and fit your padlock first (Lock Out Tag Out), then confirm")
            was = self.mode
            self.mode = mode
            if self.state == "RUNNING":
                self.stop_category = 2
            if mode == MAINTENANCE:
                self.state = "ISOLATED"
                self.checklist_ok = False
                self.checklist_for = None
                self._event("MAINTENANCE: machine isolated and locked off", "warn")
            else:
                self.state = "NOT_RESET"
                self._event(f"mode {was} -> {mode}: machine stopped, press Reset")
            return self.status()

    def reset(self, who="panel"):
        """Clear latched stops - only if every cause has gone. Never starts the machine."""
        with self.lock:
            if self.mode == MAINTENANCE:
                return False, ["machine is isolated for maintenance - leave Maintenance mode first"]
            blockers = self._reset_blockers()
            if blockers:
                self._event("reset refused: " + "; ".join(blockers), "warn")
                return False, blockers
            cleared = ", ".join(self.latched) or "nothing latched"
            self.latched.clear()
            self.state = "READY"
            self.stop_category = None
            self._event(f"RESET by {who} (cleared: {cleared}) - press Start when ready")
            return True, []

    def start(self, who="panel"):
        with self.lock:
            self._evaluate()
            why = []
            if self.mode == MAINTENANCE:
                why.append("machine is isolated for maintenance")
            if self.state in ("ESTOP", "FAULT", "NOT_RESET"):
                why.append("press Reset first")
            if self.job is None:
                why.append("plan a job first (Machine tab)")
            elif not self.checklist_ok:
                why.append(f"confirm the pre-start checklist for this job ('{self.job['name']}')")
            why += [b for b in self._reset_blockers() if b not in why]
            if why:
                self._event("start refused: " + "; ".join(why), "warn")
                return False, why
            if self.state != "RUNNING":
                self.state = "RUNNING"
                self.stop_category = None
                if self.job["state"] != "running":
                    self.job["runs"] += 1
                self.job.update(state="running", started=True)
                self._event(f"START ({self.mode}) by {who}: '{self.job['name']}'")
            return True, []

    def stop(self, who="panel", reason="stop button"):
        """Normal operational stop (category 2): Start continues."""
        with self.lock:
            if self.state == "RUNNING":
                self.state = "PAUSED"
                self.stop_category = 2
                self._event(f"stop ({reason}) by {who}")

    def finished(self):
        """The job ran to the end. The next run - of this job or another - needs a new checklist:
        the outfeed table must be cleared, the scrap tray emptied, the cell walked round."""
        with self.lock:
            if self.state in ("RUNNING", "PAUSED"):
                self.state = "READY"
            if self.job and self.job["state"] != "finished":
                self.job["state"] = "finished"
                self.checklist_ok = False
                self.checklist_for = None
                self._event(f"job finished: '{self.job['name']}' - clear the outfeed table and scrap tray, "
                            "then confirm the checklist before the next job")

    def tick(self, client="screen", enable=False, playback=None):
        """The operator screen checks in (watchdog) and, in Manual, holds the enable button."""
        with self.lock:
            now = time.time()
            self.last_beat = now
            if enable:
                self.enable_until = now + 0.35
            if playback is not None:
                self.playback = playback
            return self.status()

    # ---------------------------------------------------------------- logic
    def _camera(self):
        if not self.vision:
            return {"enabled": False}
        try:
            return self.vision.status()
        except Exception:                      # noqa: BLE001 - a broken camera must not break safety
            return {"enabled": False, "error": True}

    def _camera_ok(self, cam):
        return bool(cam.get("enabled") and cam.get("has_frame") and cam.get("frame_age", 99) <= self.cfg["camera_stale_s"])

    def _reset_blockers(self):
        cam = self._camera()
        out = []
        if self.estop_sources:
            out.append("release the E-stop (" + ", ".join(sorted(self.estop_sources)) + ")")
        if self.mode == AUTO and not self.inputs["gate_closed"]:
            out.append("close the gate")
        if self.mode == AUTO and not self.inputs["curtain_clear"]:
            out.append("clear the light curtain")
        if self.mode == AUTO and cam.get("in_danger"):
            out.append("the camera still sees someone in the danger zone")
        if self.cfg["require_camera"] and not self._camera_ok(cam):
            out.append("the camera must be running (safety.require_camera)")
        if self.cfg["require_extraction"] and not self.inputs["extraction_on"]:
            out.append("switch on the fume extraction")
        if not self.gpio_ok:
            out.append("fix the safety input wiring")
        if not self.inputs["bed_clear"] or (self.cfg.get("camera_object_stop") and cam.get("bed_blocked")):
            out.append("take the object off the bed" + (f" (camera 1 sees: {', '.join(cam.get('objects_on_bed') or [])})"
                                                         if cam.get("bed_blocked") else ""))
        if not self.inputs["load_secure"]:
            out.append("set the Handler's part down and check the magnet")
        if not self.inputs["torch_ok"]:
            out.append("re-seat the torch breakaway mount")
        if not self.inputs["no_fire"]:
            out.append("the fire detector still sees flame or smoke")
        return out

    def _latch(self, code, detail=""):
        if code in self.latched:
            return
        self.latched[code] = time.time()
        was_running = self.state == "RUNNING"
        if code == "ESTOP":
            self.state = "ESTOP"
            self.stop_category = self.cfg["estop_category"]
        else:
            if self.state != "ESTOP" and self.mode != MAINTENANCE:
                self.state = "FAULT"
            cat = STOP_CATEGORY.get(code, self.cfg["protective_stop_category"])
            self.stop_category = cat if was_running else self.stop_category
        text, ref = FAULTS[code]
        self._event(f"STOP: {detail or text} [{ref}]" + (f" - category {self.stop_category} stop" if was_running else ""), "stop")

    def _evaluate(self):
        """Watch every input and latch stops. Called on every status request and by a 10 Hz watchdog."""
        now = time.time()
        if self.mode == MAINTENANCE:
            self.state = "ISOLATED"
            return
        if self.estop_sources:
            self._latch("ESTOP")
        cam = self._camera()
        active = self.state in ("RUNNING", "PAUSED", "READY")
        if self.mode == AUTO and active:
            if not self.inputs["gate_closed"]:
                self._latch("GATE")
            if not self.inputs["curtain_clear"]:
                self._latch("CURTAIN")
            if cam.get("in_danger"):
                self._latch("PERSON")
        if self.state == "RUNNING":
            if self.cfg["require_camera"] and not self._camera_ok(cam):
                self._latch("CAMERA")
            if self.last_beat is None or now - self.last_beat > self.cfg["heartbeat_timeout_s"]:
                self._latch("HEARTBEAT")
            if self.cfg["require_extraction"] and not self.inputs["extraction_on"]:
                self._latch("EXTRACTION")
            if not self.inputs["bed_clear"] or (self.cfg.get("camera_object_stop") and cam.get("bed_blocked")):
                self._latch("OBJECT")
        if active:                              # the Handler can be holding a part while paused
            if not self.inputs["load_secure"]:
                self._latch("LOAD")
            if not self.inputs["torch_ok"]:
                self._latch("TORCH")
        if not self.inputs["no_fire"]:          # a fire matters whatever the machine is doing
            self._latch("FIRE")

    # ---------------------------------------------------------------- outputs
    def status(self):
        with self.lock:
            self._evaluate()
            now = time.time()
            cam = self._camera()
            enable = now < self.enable_until
            running = self.state == "RUNNING" and not self.latched
            may_move = running and (self.mode == AUTO or (self.mode == MANUAL and enable))
            if not may_move:
                speed = 0.0
            elif self.mode == MANUAL:
                speed = min(1.0, self.cfg["manual_speed_mm_s"] / GANTRY_MAX_MM_S)
            elif cam.get("in_warning"):
                speed = self.cfg["warning_speed"]
            else:
                speed = 1.0
            torch = may_move and (self.inputs["extraction_on"] or not self.cfg["require_extraction"])
            red = self.state in ("ESTOP", "FAULT")
            lamps = {"red": red, "amber": (not red) and (self.state in ("PAUSED", "READY") or speed < 1.0 or self.mode != AUTO),
                     "green": may_move and speed >= 1.0, "blue": self.state in ("ESTOP", "FAULT", "NOT_RESET")}
            blockers = self._reset_blockers()
            return {
                "state": self.state, "mode": self.mode, "may_move": may_move, "speed_factor": round(speed, 3),
                "torch_allowed": torch, "stop_category": self.stop_category, "enable_held": enable,
                "estop_pressed": bool(self.estop_sources), "estop_sources": sorted(self.estop_sources),
                "latched": [{"code": c, "text": FAULTS[c][0], "ref": FAULTS[c][1], "since": round(t, 1),
                             "decision": DECISIONS.get(c)}
                            for c, t in self.latched.items()],
                "inputs": dict(self.inputs), "input_source": dict(self.input_source),
                "camera": {k: cam.get(k) for k in ("enabled", "in_warning", "in_danger", "people", "detector",
                                                   "objects_on_bed", "bed_blocked")},
                "checklist_ok": self.checklist_ok, "checklist": self.cfg["checklist"],
                "checklist_for": self.checklist_for, "job": dict(self.job) if self.job else None,
                "can_reset": not blockers and self.mode != MAINTENANCE, "reset_blockers": blockers,
                "lamps": lamps, "events": list(self.events)[:40],
                "safety_distance": safety_distance(self.cfg["light_curtain"]),
            }

    def watchdog(self, period=0.1):
        """Background thread: keeps checking even if nobody asks for the status."""
        def run():
            while True:
                with self.lock:
                    self._evaluate()
                time.sleep(period)
        threading.Thread(target=run, daemon=True).start()


def safety_distance(lc):
    """Minimum distance from a light curtain to the hazard, BS EN ISO 13855:
        S = K * T + C,  T = machine stopping time + curtain response time,
        K = 2000 mm/s (if S comes out at 500 mm or less, minimum 100 mm) otherwise 1600 mm/s,
        C = 8 * (d - 14) for a curtain resolution d up to 40 mm (finger/hand detection)."""
    T = (lc["machine_stop_ms"] + lc["response_ms"]) / 1000.0
    d = lc["resolution_mm"]
    C = 8 * (d - 14) if d <= 40 else 850
    S = 2000 * T + C
    if S > 500:
        S = max(1600 * T + C, 500)
        K = 1600
    else:
        S = max(S, 100)
        K = 2000
    return {"S_mm": round(S), "K": K, "T_s": round(T, 3), "C_mm": round(C), "d_mm": d,
            "formula": f"S = {K} x {T:.3f} + {C:.0f} = {S:.0f} mm (BS EN ISO 13855)"}
