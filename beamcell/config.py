"""
Settings from config/cell.toml, with safe defaults for anything left out.

    from beamcell.config import CONFIG
    CONFIG["safety"]["warning_speed"]
"""
import copy
import os

try:
    import tomllib                      # Python 3.11+
except ImportError:                     # pragma: no cover - older Python
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "config", "cell.toml")

DEFAULTS = {
    "safety": {
        "estop_category": 0, "protective_stop_category": 1, "require_extraction": True,
        "require_camera": False, "camera_stale_s": 1.5, "heartbeat_timeout_s": 2.0,
        "warning_speed": 0.25, "manual_speed_mm_s": 250, "log_file": "logs/safety_log.jsonl",
        "checklist": ["Fence and gate closed", "Nobody inside the cell", "Fume extraction running",
                      "E-stops tested this shift", "PPE on"],
        "light_curtain": {"resolution_mm": 30, "response_ms": 20, "machine_stop_ms": 600},
    },
    "camera": {"source": "0", "autostart": False, "model": "",
               "warning_zone": [0.05, 0.15, 0.95, 1.0], "danger_zone": [0.25, 0.35, 0.75, 1.0]},
    "gpio": {"enabled": False, "estop_pin": 0, "gate_pin": 0, "curtain_pin": 0, "reset_pin": 0, "poll_hz": 50},
    "assistant": {"enabled": False, "model": "claude-opus-5-5", "effort": "low", "send_camera": True},
    "server": {"port": 8080},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def problems(cfg):
    """Plain-English list of anything wrong in the settings."""
    out = []
    s = cfg["safety"]
    if s["estop_category"] not in (0, 1):
        out.append("safety.estop_category must be 0 or 1 (BS EN 60204-1: an E-stop is category 0 or 1)")
    if s["protective_stop_category"] not in (0, 1, 2):
        out.append("safety.protective_stop_category must be 0, 1 or 2")
    if not 0 < s["warning_speed"] <= 1:
        out.append("safety.warning_speed must be between 0 and 1")
    if s["manual_speed_mm_s"] > 250:
        out.append("safety.manual_speed_mm_s above 250 mm/s is not 'reduced speed' (BS EN ISO 10218-1)")
    for name in ("warning_zone", "danger_zone"):
        z = cfg["camera"][name]
        if len(z) != 4 or not (0 <= z[0] < z[2] <= 1 and 0 <= z[1] < z[3] <= 1):
            out.append(f"camera.{name} must be [left, top, right, bottom] fractions between 0 and 1")
    g = cfg["gpio"]
    pins = [g[k] for k in ("estop_pin", "gate_pin", "curtain_pin", "reset_pin") if g[k]]
    if len(pins) != len(set(pins)):
        out.append("gpio: two inputs use the same pin")
    if g["enabled"] and not g["estop_pin"]:
        out.append("gpio.enabled is true but estop_pin is 0 - wire the E-stop's auxiliary contact first")
    if cfg["assistant"]["effort"] not in ("low", "medium", "high", "xhigh", "max"):
        out.append("assistant.effort must be low, medium, high, xhigh or max")
    return out


def load(path=PATH):
    data = {}
    if os.path.exists(path):
        if tomllib is None:
            raise RuntimeError("config/cell.toml needs Python 3.11 or newer")
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    return _merge(DEFAULTS, data)


CONFIG = load()
