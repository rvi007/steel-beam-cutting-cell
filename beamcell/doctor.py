"""
System check: is this computer ready to run the cell, and what's left to set up?

    python3 -m beamcell.doctor            print the check and a plan
    python3 -m beamcell.doctor --save     also write docs/SYSTEM_CHECK.md (push it so a cloud
                                          session can read your exact setup)

It only LOOKS - it never installs or changes anything.
"""
import glob
import importlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

from beamcell.config import CONFIG, PATH as CONFIG_PATH, ROOT, problems

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "info"


def _read(path):
    try:
        with open(path) as fh:
            return fh.read().strip("\x00\n ")
    except OSError:
        return ""


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def checks():
    out = []

    def add(area, status, text, fix=""):
        out.append({"area": area, "status": status, "text": text, "fix": fix})

    # ---------------------------------------------------------------- board and OS
    model = _read("/proc/device-tree/model") or platform.machine()
    add("Board", INFO, model)
    rel = _read("/etc/nv_tegra_release").split("\n")[0]
    if rel:
        add("Jetson Linux", INFO, rel)
    add("OS", INFO, f"{platform.system()} {platform.release()}")
    mem = {}
    for line in _read("/proc/meminfo").split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0]) // 1024
    if mem:
        avail, total = mem.get("MemAvailable", 0), mem.get("MemTotal", 0)
        add("Memory", OK if avail > 800 else WARN, f"{avail} MB free of {total} MB, swap free {mem.get('SwapFree', 0)} MB",
            "" if avail > 800 else "Close other programs (browsers, old windows) before running the cell, or open the app from a laptop")
    du = shutil.disk_usage(ROOT)
    add("Disk", OK if du.free > 2e9 else WARN, f"{du.free / 1e9:.0f} GB free")

    # ---------------------------------------------------------------- Python and libraries
    v = sys.version_info
    add("Python", OK if v >= (3, 11) else FAIL, sys.version.split()[0],
        "" if v >= (3, 11) else "Python 3.11 or newer is needed (it reads config/cell.toml)")
    for name, need, why in (("numpy", True, "the planner"), ("cv2", False, "the camera"),
                            ("anthropic", False, "the optional Claude advisor"), ("Jetson.GPIO", False, "real E-stop / gate wiring")):
        try:
            mod = importlib.import_module(name)
            add(f"{name}", OK, f"version {getattr(mod, '__version__', getattr(mod, 'VERSION', '?'))} - for {why}")
        except Exception:                            # noqa: BLE001 - any import problem
            add(f"{name}", FAIL if need else WARN, f"not installed - needed for {why}",
                {"numpy": "sudo apt install python3-numpy", "cv2": "sudo apt install python3-opencv",
                 "anthropic": "pip install --user anthropic (only if you want the advisor)",
                 "Jetson.GPIO": "sudo apt install python3-jetson-gpio (only for wired buttons)"}[name])
    try:
        import cv2
        info = cv2.getBuildInformation()
        gst = "GStreamer:                   YES" in info or "GStreamer: YES" in info.replace("  ", "")
        add("OpenCV HOG", OK if hasattr(cv2, "HOGDescriptor") else WARN,
            "built-in people detector available" if hasattr(cv2, "HOGDescriptor") else "no HOG in this OpenCV - put a YOLO .onnx in models/")
        add("OpenCV GStreamer", OK if gst else WARN, "yes - CSI cameras will work" if gst else "no - USB cameras only")
    except ImportError:
        pass

    # ---------------------------------------------------------------- cameras, models, GPIO
    vids = sorted(glob.glob("/dev/video*"))
    add("Cameras", OK if vids else WARN, ", ".join(vids) or "no /dev/video* devices",
        "" if vids else "Plug in a USB camera, or connect a CSI camera and reboot")
    if shutil.which("gst-inspect-1.0"):
        csi = "nvarguscamerasrc" in _run(["gst-inspect-1.0", "nvarguscamerasrc"])
        add("CSI camera support", OK if csi else INFO, "nvarguscamerasrc found" if csi else "nvarguscamerasrc not found")
    models = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "models", "*.onnx")))
    add("YOLO models", OK if models else WARN, ", ".join(models) or "none in models/",
        "" if models else "Export yolo11n to ONNX on a PC and copy it to models/ (docs/JETSON_SETUP.md); HOG works meanwhile")
    chips = sorted(glob.glob("/dev/gpiochip*"))
    add("GPIO chips", INFO, ", ".join(chips) or "none")
    try:
        import grp
        groups = {grp.getgrgid(g).gr_name for g in os.getgroups()}
        add("User groups", OK if "gpio" in groups or not CONFIG["gpio"]["enabled"] else WARN, ", ".join(sorted(groups)),
            "" if "gpio" in groups or not CONFIG["gpio"]["enabled"] else "sudo usermod -aG gpio $USER, then log out and in")
    except (ImportError, KeyError):
        pass

    # ---------------------------------------------------------------- settings and services
    probs = problems(CONFIG)
    add("config/cell.toml", OK if os.path.exists(CONFIG_PATH) and not probs else (WARN if not probs else FAIL),
        "found, no problems" if os.path.exists(CONFIG_PATH) and not probs else ("; ".join(probs) or "missing - defaults used"))
    g = CONFIG["gpio"]
    add("Wired safety inputs", OK if g["enabled"] else WARN,
        f"E-stop pin {g['estop_pin']}, gate pin {g['gate_pin']}, curtain pin {g['curtain_pin']}, reset pin {g['reset_pin']}"
        if g["enabled"] else "not wired - the E-stop and gate are on-screen only",
        "" if g["enabled"] else "For a physical demo, wire an E-stop's auxiliary contact (docs/SAFETY.md, 'Wiring')")
    port = CONFIG["server"]["port"]
    s = socket.socket()
    try:
        s.bind(("0.0.0.0", port))
        add("Port", OK, f"{port} is free")
    except OSError:
        add("Port", WARN, f"{port} is in use - is the app already running?", "Stop it, or use ./start.sh --port 8090")
    finally:
        s.close()
    log = os.path.join(ROOT, CONFIG["safety"]["log_file"])
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a"):
            pass
        add("Safety log", OK, os.path.relpath(log, ROOT))
    except OSError as e:
        add("Safety log", FAIL, f"can't write {log}: {e}")
    a = CONFIG["assistant"]
    if a["enabled"]:
        key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        add("Advisor", OK if key else WARN, f"on, model {a['model']}, API key {'set' if key else 'NOT set'}",
            "" if key else "export ANTHROPIC_API_KEY=... (docs/ASSISTANT.md)")
    else:
        add("Advisor", INFO, "off (config: [assistant] enabled = false)")
    browser = shutil.which("chromium-browser") or shutil.which("chromium") or shutil.which("google-chrome")
    add("Browser", OK if browser else WARN, browser or "no Chromium found", "" if browser else "Open the app from another computer instead")
    return out


def plan(results):
    steps = [f"{r['area']}: {r['fix']}" for r in results if r["status"] in (FAIL, WARN) and r["fix"]]
    steps += ["Run the cell: ./start.sh, open http://localhost:8080",
              "Safety tab: Reset, tick the checklist, Start - try the E-stop (Esc), gate and light curtain",
              "Before any real hardware: do the risk assessment in docs/SAFETY.md with a competent person"]
    return steps


def report(results):
    width = max(len(r["area"]) for r in results)
    lines = [f"Beam Cell system check - {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for r in results:
        lines.append(f"[{r['status']:>4}] {r['area']:<{width}}  {r['text']}")
    lines += ["", "Plan:"] + [f"  {i + 1}. {s}" for i, s in enumerate(plan(results))]
    return "\n".join(lines)


def main():
    results = checks()
    text = report(results)
    print(text)
    if "--save" in sys.argv:
        path = os.path.join(ROOT, "docs", "SYSTEM_CHECK.md")
        with open(path, "w") as fh:
            fh.write("# System check\n\nWritten by `python3 -m beamcell.doctor --save`.\n\n```\n" + text + "\n```\n")
        print(f"\nSaved to {os.path.relpath(path, ROOT)} - commit and push it to share your setup.")
    return 1 if any(r["status"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
