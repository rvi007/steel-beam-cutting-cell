"""
LESSON 1 - Joint control (moving each axis by hand)

Run:   python3 lesson01_joints.py

What to try:
  1. Move J1 (base). The whole arm spins around the vertical Z axis.
  2. Move J2 (shoulder) and J3 (elbow). These lift and reach - they set WHERE the tool is.
  3. Move J4, J5, J6 (wrist). The tip barely moves, but the tool's red/green/blue
     arrows rotate - the wrist sets the tool's ORIENTATION.
  4. Watch the "Tool position" text: that is forward kinematics -
     joint angles in, tool position out.
"""
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, Slider

import robot

HOME_DEG = [0, -90, 0, -90, 0, 0]  # a neat "standing up" starting pose

fig = plt.figure("Lesson 1 - Joint control", figsize=(10, 8))
ax = fig.add_axes([0.0, 0.32, 1.0, 0.66], projection="3d")
info = fig.text(0.02, 0.30, "", family="monospace", fontsize=10)

sliders = []
for i, name in enumerate(robot.JOINT_NAMES):
    lo, hi = robot.JOINT_LIMITS_DEG[i]
    s_ax = fig.add_axes([0.18, 0.24 - i * 0.035, 0.62, 0.025])
    sliders.append(Slider(s_ax, name, lo, hi, valinit=HOME_DEG[i], valfmt="%4.0f°"))

home_btn = Button(fig.add_axes([0.84, 0.05, 0.12, 0.05]), "Home")


def update(_=None):
    angles = np.radians([s.val for s in sliders])
    frames = robot.forward_kinematics(angles)

    elev, azim = ax.elev, ax.azim  # keep the camera where the user left it
    ax.cla()
    robot.setup_axes(ax)
    robot.draw_robot(ax, frames)
    ax.view_init(elev, azim)

    x, y, z = frames[-1][:3, 3]
    info.set_text(f"Tool position:  X={x:+.3f} m   Y={y:+.3f} m   Z={z:+.3f} m")
    fig.canvas.draw_idle()


def go_home(_):
    for s, v in zip(sliders, HOME_DEG):
        s.set_val(v)


for s in sliders:
    s.on_changed(update)
home_btn.on_clicked(go_home)

ax.view_init(25, -60)
update()
plt.show()
