"""
INVERSE KINEMATICS - tell the robot WHERE to go, it works out HOW.

Run:   python3 ik_target.py

Until now you set joint angles and saw where the tool ended up (forward kinematics).
Here it's the other way round: you place a TARGET (the red ball), and the robot
solves for all 6 joint angles that put the tool on it, pointing straight down.

  Knob / "Target angle" slider  -> swings the target around the base
  "Reach" slider                -> how far out the target is
  "Height" slider               -> how high the target is

The real servo is J1, so it turns to follow the target.

Things to notice:
  1. J1 is NOT the same as the target angle. The shoulder sits 0.109 m to the side,
     so the base has to turn a bit extra. Watch the "J1 offset" number.
  2. Make Reach large (try 0.85) - the target goes red: UNREACHABLE.
     The arm stretches as far as it can toward it.
  3. Change Height: J2, J3 and J4 all change together to keep the tool pointing down.
     One small target move = all six joints solve together.
  4. If J1 needs more than ±90°, the real servo stops at its limit
     ("SERVO LIMIT") while the 3D robot keeps going.
"""
import glob

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Slider

import robot

SEED_DEG = [0, -60, 90, -120, -90, 0]  # starting pose, tool pointing down
REACHED_M = 0.002                      # within 2 mm counts as reached


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


arduino = find_arduino()
state = {"knob": None, "last_knob": None, "last_sent": None, "buffer": "",
         "q": np.radians(SEED_DEG), "err": 0.0, "trail": []}

fig = plt.figure("Inverse kinematics - reach the target", figsize=(10, 8.5))
ax = fig.add_axes([0.0, 0.27, 0.72, 0.71], projection="3d")
status = fig.text(0.02, 0.02, "", family="monospace", fontsize=10)
panel = fig.text(0.73, 0.93, "", family="monospace", fontsize=10, va="top")

angle = Slider(fig.add_axes([0.17, 0.19, 0.55, 0.03]), "Target angle", -90, 90, valinit=0, valfmt="%4.0f°")
reach = Slider(fig.add_axes([0.17, 0.14, 0.55, 0.03]), "Reach (m)", 0.25, 0.95, valinit=0.5, valfmt="%.2f")
height = Slider(fig.add_axes([0.17, 0.09, 0.55, 0.03]), "Height (m)", 0.0, 0.7, valinit=0.2, valfmt="%.2f")
ax.view_init(30, -60)


def send_servo(j1_deg):
    """Send J1 to the servo, clamped to what the servo can do. Returns True if clamped."""
    clamped = float(np.clip(j1_deg, -90, 90))
    servo_deg = int(round(clamped + 90))  # robot -90..90 -> servo 0..180
    if arduino and servo_deg != state["last_sent"]:
        arduino.write(f"S{servo_deg}\n".encode())
        state["last_sent"] = servo_deg
    return clamped != j1_deg


def read_knob():
    if not arduino:
        return
    state["buffer"] += arduino.read(arduino.in_waiting or 1).decode(errors="ignore")
    *lines, state["buffer"] = state["buffer"].split("\n")
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("K") and ln[1:].isdigit():
            state["knob"] = int(ln[1:]) - 90


def target_xyz():
    """Target angle 0° is straight out in front of the robot (the -X direction)."""
    a = np.radians(angle.val)
    return np.array([-reach.val * np.cos(a), -reach.val * np.sin(a), height.val])


def fresh_seed(target):
    """A good starting guess: base turned toward the target (plus the shoulder-offset
    correction), everything else in the standard tool-down pose."""
    r = max(np.hypot(target[0], target[1]), 0.12)
    j1 = np.arctan2(-target[1], -target[0]) - np.arcsin(min(robot.DH_D[3] / r, 1.0))
    return np.radians(SEED_DEG) + np.array([j1, 0, 0, 0, 0, 0])


def solve(target):
    """Try from the last answer first (smooth motion). If that fails or the arm has
    flipped round, start again from a fresh guess aimed at the target."""
    seed = fresh_seed(target)
    q, err = robot.inverse_kinematics(target, state["q"])
    flipped = abs((q[0] - seed[0] + np.pi) % (2 * np.pi) - np.pi) > np.radians(45)
    if err >= REACHED_M or flipped:
        q2, err2 = robot.inverse_kinematics(target, seed)
        if err2 <= err or flipped:
            q, err = q2, err2
    return q, err


def solve_and_draw(_=None):
    target = target_xyz()
    state["q"], state["err"] = solve(target)
    reached = state["err"] < REACHED_M

    q_deg = np.degrees(state["q"])
    limited = send_servo(q_deg[0])

    frames = robot.forward_kinematics(state["q"])
    tip = frames[-1][:3, 3]
    if reached:
        state["trail"] = (state["trail"] + [tip])[-200:]

    elev, azim = ax.elev, ax.azim
    ax.cla()
    robot.setup_axes(ax)
    color = "#2ca02c" if reached else "#d62728"
    ax.scatter(*target, color=color, s=160, alpha=0.5)
    ax.plot([target[0]] * 2, [target[1]] * 2, [0, target[2]], "--", color=color, linewidth=1)
    if len(state["trail"]) > 1:
        t = np.array(state["trail"])
        ax.plot(t[:, 0], t[:, 1], t[:, 2], ":", color="#e67e22", linewidth=1.5)
    robot.draw_robot(ax, frames)
    ax.view_init(elev, azim)

    rows = ["JOINTS (solved)"] + [f"{robot.JOINT_NAMES[i]:<12}{q_deg[i]:+5.0f}°" for i in range(6)]
    rows += ["", "TARGET",
             f"X {target[0]:+.3f}  Y {target[1]:+.3f}",
             f"Z {target[2]:+.3f} m",
             "", f"Error   {state['err'] * 1000:7.1f} mm",
             f"J1 offset {q_deg[0] - angle.val:+5.1f}°",
             "", "REACHED" if reached else "UNREACHABLE"]
    if limited:
        rows.append("SERVO LIMIT (±90°)")
    panel.set_text("\n".join(rows))
    panel.set_color("#000000" if reached and not limited else "#d62728")

    link = "Arduino CONNECTED" if arduino else "DEMO (no Arduino)"
    knob = "--" if state["knob"] is None else f"{state['knob']:+4d}°"
    servo = np.clip(q_deg[0], -90, 90) + 90
    status.set_text(f"{link}   knob={knob}   servo={servo:3.0f}°")
    fig.canvas.draw_idle()


for s in (angle, reach, height):
    s.on_changed(solve_and_draw)
solve_and_draw()

# Main loop: about 20 updates per second
while plt.fignum_exists(fig.number):
    read_knob()
    if state["knob"] is not None and (state["last_knob"] is None or abs(state["knob"] - state["last_knob"]) >= 2):
        if state["last_knob"] is not None:
            angle.set_val(state["knob"])  # knob moves the TARGET, IK moves the robot
        state["last_knob"] = state["knob"]
    plt.pause(0.05)

if arduino:
    arduino.close()
