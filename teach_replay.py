"""
TEACH AND REPLAY - program the robot the way factories do.

Run:   python3 teach_replay.py

1. TEACH:  turn the knob (or drag the slider) to a position, press "Record".
           Do this for several positions - each one is a waypoint.
2. REPLAY: press "Play". The real servo and the 3D robot move through every
           waypoint on their own, with smooth start/stop on each move.
           Tick "Loop" to repeat forever (like a robot on a production line).
3. Waypoints are saved to waypoints.json, so they are still there next time.

New ideas compared to digital_twin.py:
  - waypoints        a robot program is just a list of positions
  - trajectories     moving smoothly between them (ease in / ease out)
  - speed limit      every move takes time = distance / speed
  - state machine    the program is either TEACHING or PLAYING

Hardware is the same as digital_twin.py (servo on pin 9, knob on A0).
"""
import glob
import json
import os
import time

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, CheckButtons, Slider

import robot

POSE_DEG = [0, -60, 60, -90, -90, 0]  # same reaching pose as digital_twin.py
SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "waypoints.json")
DWELL_S = 0.4  # pause at each waypoint, like a real robot settling


def find_arduino():
    try:
        import serial
    except ImportError:
        return None
    for port in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
        try:
            conn = serial.Serial(port, 115200, timeout=0)
            print(f"Connected to Arduino on {port}")
            return conn
        except (serial.SerialException, PermissionError) as e:
            print(f"Found {port} but cannot open it: {e}")
    print("No Arduino found - running in DEMO mode (screen only).")
    return None


def load_waypoints():
    try:
        with open(SAVE_FILE) as f:
            return [float(w) for w in json.load(f)]
    except (OSError, ValueError):
        return []


def save_waypoints():
    with open(SAVE_FILE, "w") as f:
        json.dump(state["waypoints"], f)


arduino = find_arduino()
state = {
    "knob": None, "last_knob": None, "last_sent": None, "buffer": "",
    "waypoints": load_waypoints(),
    "mode": "TEACH",       # TEACH or PLAY
    "move": None,          # current move: (start_deg, end_deg, start_time, duration)
    "target_index": 0,     # which waypoint we are heading to
    "dwell_until": 0.0,
    "trail": [],
}

fig = plt.figure("Teach and replay", figsize=(10, 8))
ax = fig.add_axes([0.0, 0.25, 0.72, 0.73], projection="3d")
status = fig.text(0.02, 0.02, "", family="monospace", fontsize=10)
listing = fig.text(0.74, 0.95, "", family="monospace", fontsize=10, va="top")

j1 = Slider(fig.add_axes([0.15, 0.17, 0.55, 0.03]), "J1 Base", -90, 90, valinit=0, valfmt="%4.0f°")
speed = Slider(fig.add_axes([0.15, 0.12, 0.55, 0.03]), "Speed °/s", 10, 180, valinit=60, valfmt="%3.0f")
rec_btn = Button(fig.add_axes([0.74, 0.17, 0.11, 0.05]), "Record")
play_btn = Button(fig.add_axes([0.87, 0.17, 0.11, 0.05]), "Play")
undo_btn = Button(fig.add_axes([0.74, 0.10, 0.11, 0.05]), "Undo")
clear_btn = Button(fig.add_axes([0.87, 0.10, 0.11, 0.05]), "Clear")
loop_box = CheckButtons(fig.add_axes([0.74, 0.04, 0.24, 0.05]), ["Loop"], [False])
ax.view_init(30, -60)


# ---------------- talking to the Arduino ----------------

def send_servo(j1_deg):
    servo_deg = int(round(j1_deg + 90))  # robot -90..90  ->  servo 0..180
    if arduino and servo_deg != state["last_sent"]:
        arduino.write(f"S{servo_deg}\n".encode())
        state["last_sent"] = servo_deg


def read_knob():
    if not arduino:
        return
    state["buffer"] += arduino.read(arduino.in_waiting or 1).decode(errors="ignore")
    *lines, state["buffer"] = state["buffer"].split("\n")
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("K") and ln[1:].isdigit():
            state["knob"] = int(ln[1:]) - 90


# ---------------- drawing ----------------

def tool_point(j1_deg):
    angles = list(POSE_DEG)
    angles[0] = j1_deg
    return robot.forward_kinematics(np.radians(angles))


def redraw():
    frames = tool_point(j1.val)
    elev, azim = ax.elev, ax.azim
    ax.cla()
    robot.setup_axes(ax)

    # Waypoints as numbered green dots where the tool will go
    for n, w in enumerate(state["waypoints"], 1):
        p = tool_point(w)[-1][:3, 3]
        ax.scatter(*p, color="#2ca02c", s=50)
        ax.text(*p + [0, 0, 0.04], str(n), color="#2ca02c", fontsize=9)
    if len(state["trail"]) > 1:
        t = np.array(state["trail"])
        ax.plot(t[:, 0], t[:, 1], t[:, 2], ":", color="#e67e22", linewidth=1.5)

    robot.draw_robot(ax, frames)
    ax.view_init(elev, azim)

    link = "Arduino CONNECTED" if arduino else "DEMO (no Arduino)"
    knob = "--" if state["knob"] is None else f"{state['knob']:+4d}°"
    mode = state["mode"]
    if mode == "PLAY":
        mode += f" -> point {state['target_index'] + 1}/{len(state['waypoints'])}"
    status.set_text(f"{link}   {mode}   J1={j1.val:+4.0f}°   knob={knob}")

    lines = ["WAYPOINTS"] + [
        f"{'>' if state['mode'] == 'PLAY' and n == state['target_index'] else ' '}"
        f"{n + 1:2d}: {w:+5.0f}°" for n, w in enumerate(state["waypoints"])
    ]
    listing.set_text("\n".join(lines) if state["waypoints"] else "WAYPOINTS\n (none yet -\n  press Record)")
    fig.canvas.draw_idle()


# ---------------- buttons ----------------

def on_slider(_):
    send_servo(j1.val)
    redraw()


def record(_):
    if state["mode"] == "TEACH":
        state["waypoints"].append(round(j1.val))
        save_waypoints()
        redraw()


def undo(_):
    if state["mode"] == "TEACH" and state["waypoints"]:
        state["waypoints"].pop()
        save_waypoints()
        redraw()


def clear(_):
    if state["mode"] == "TEACH":
        state["waypoints"] = []
        state["trail"] = []
        save_waypoints()
        redraw()


def play(_):
    if state["mode"] == "PLAY":  # button doubles as Stop
        stop_playing()
        return
    if len(state["waypoints"]) < 2:
        status.set_text("Record at least 2 waypoints first.")
        fig.canvas.draw_idle()
        return
    state["mode"] = "PLAY"
    state["trail"] = []
    state["target_index"] = 0
    start_move(0)
    play_btn.label.set_text("Stop")


def stop_playing():
    state["mode"] = "TEACH"
    state["move"] = None
    state["last_knob"] = state["knob"]  # don't jump to the knob the moment we stop
    play_btn.label.set_text("Play")
    redraw()


def start_move(index):
    """Plan a smooth move from where J1 is now to waypoint[index]."""
    start, end = j1.val, state["waypoints"][index]
    duration = max(abs(end - start) / speed.val, 0.05)  # time = distance / speed
    state["move"] = (start, end, time.time(), duration)
    state["target_index"] = index


def step_playback():
    """Called ~20 times a second while playing: work out where J1 should be NOW."""
    now = time.time()
    if now < state["dwell_until"]:
        return
    start, end, t0, duration = state["move"]
    s = min((now - t0) / duration, 1.0)
    s = 3 * s**2 - 2 * s**3  # ease in / ease out: slow start, slow stop, no jerk
    j1.set_val(start + (end - start) * s)  # moves 3D robot and sends to the servo
    state["trail"].append(tool_point(j1.val)[-1][:3, 3])

    if s >= 1.0:  # arrived at this waypoint
        state["dwell_until"] = now + DWELL_S
        nxt = state["target_index"] + 1
        if nxt >= len(state["waypoints"]):
            if not loop_box.get_status()[0]:
                stop_playing()
                return
            nxt = 0
            state["trail"] = []
        start_move(nxt)
        state["move"] = (state["move"][0], state["move"][1], state["dwell_until"], state["move"][3])


j1.on_changed(on_slider)
rec_btn.on_clicked(record)
play_btn.on_clicked(play)
undo_btn.on_clicked(undo)
clear_btn.on_clicked(clear)
redraw()

# Main loop: about 20 updates per second
while plt.fignum_exists(fig.number):
    read_knob()
    if state["mode"] == "PLAY":
        step_playback()
    elif state["knob"] is not None and (state["last_knob"] is None or abs(state["knob"] - state["last_knob"]) >= 2):
        if state["last_knob"] is not None:
            j1.set_val(state["knob"])
        state["last_knob"] = state["knob"]
    plt.pause(0.05)

if arduino:
    arduino.close()
