"""
DIGITAL TWIN - the real servo on the Arduino is joint J1 (base) of the 3D robot.

Run:   python3 digital_twin.py

Both work at any time:
  Drag the J1 slider on screen   -> the real servo turns.
  Turn the real potentiometer    -> the 3D robot AND the servo turn.

If no Arduino is plugged in, it runs in DEMO mode (screen only).

Angle mapping:  robot J1 = -90°..+90°   <->   servo 0°..180°
"""
import glob

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Slider

import robot

POSE_DEG = [0, -60, 60, -90, -90, 0]  # a reaching pose so base rotation is easy to see


def find_arduino():
    """Open the first USB serial port that looks like an Arduino, or return None."""
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


arduino = find_arduino()
state = {"knob": None, "last_knob": None, "last_sent": None, "buffer": ""}

fig = plt.figure("Digital twin - real servo = J1", figsize=(9, 8))
ax = fig.add_axes([0.0, 0.18, 1.0, 0.8], projection="3d")
status = fig.text(0.02, 0.02, "", family="monospace", fontsize=10)
j1 = Slider(fig.add_axes([0.15, 0.1, 0.55, 0.03]), "J1 Base", -90, 90, valinit=0, valfmt="%4.0f°")
ax.view_init(30, -60)


def send_servo(j1_deg):
    servo_deg = int(round(j1_deg + 90))  # robot -90..90  ->  servo 0..180
    if arduino and servo_deg != state["last_sent"]:
        arduino.write(f"S{servo_deg}\n".encode())
        state["last_sent"] = servo_deg


def read_knob():
    """Read all waiting lines from the Arduino, keep the newest knob value."""
    if not arduino:
        return
    state["buffer"] += arduino.read(arduino.in_waiting or 1).decode(errors="ignore")
    *lines, state["buffer"] = state["buffer"].split("\n")
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("K") and ln[1:].isdigit():
            state["knob"] = int(ln[1:]) - 90  # servo 0..180 -> robot -90..90


def redraw():
    angles = list(POSE_DEG)
    angles[0] = j1.val
    frames = robot.forward_kinematics(np.radians(angles))
    elev, azim = ax.elev, ax.azim
    ax.cla()
    robot.setup_axes(ax)
    robot.draw_robot(ax, frames)
    ax.view_init(elev, azim)
    link = "Arduino CONNECTED" if arduino else "DEMO (no Arduino)"
    knob = "--" if state["knob"] is None else f"{state['knob']:+4d}°"
    status.set_text(f"{link}   J1={j1.val:+4.0f}°   "
                    f"servo={j1.val + 90:3.0f}°   knob={knob}")
    fig.canvas.draw_idle()


def on_slider(_):
    send_servo(j1.val)
    redraw()


j1.on_changed(on_slider)
redraw()

# Main loop: about 20 updates per second, like a real control loop
while plt.fignum_exists(fig.number):
    read_knob()
    # React only when the knob really turns (2° or more), so tiny wobble is ignored
    if state["knob"] is not None and (state["last_knob"] is None or abs(state["knob"] - state["last_knob"]) >= 2):
        if state["last_knob"] is not None:  # ignore the first reading, only react to turns
            j1.set_val(state["knob"])  # moves the 3D robot, which also sends to the servo
        state["last_knob"] = state["knob"]
    plt.pause(0.05)

if arduino:
    arduino.close()
