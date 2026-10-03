"""
Simple robot-control library for the simulator.

Use it like a real robot controller:

    from sim import Robot
    bot = Robot()
    bot.move_joints([0, -90, 90, -90, -90, 0])   # degrees, smooth motion
    bot.wait(1)
    bot.home()
    bot.done()
"""
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np

import robot

HOME_DEG = [0, -90, 0, -90, 0, 0]
FPS = 30


class Robot:
    def __init__(self, speed_deg_per_s=60):
        self.speed = speed_deg_per_s
        self.joints_deg = np.array(HOME_DEG, dtype=float)
        self.trail = []  # tool-tip path, drawn as a dotted line

        self.fig = plt.figure("Robot simulator", figsize=(9, 8))
        self.ax = self.fig.add_axes([0.0, 0.08, 1.0, 0.9], projection="3d")
        self.text = self.fig.text(0.02, 0.02, "", family="monospace", fontsize=10)
        self.ax.view_init(25, -60)
        self._draw()
        plt.pause(0.5)

    # ---------- commands you use in your programs ----------

    def move_joints(self, target_deg, speed=None):
        """Move all 6 joints smoothly to target angles (degrees)."""
        target = np.array(target_deg, dtype=float)
        if target.shape != (6,):
            raise ValueError("move_joints needs exactly 6 angles, e.g. [0, -90, 0, -90, 0, 0]")
        for i, (lo, hi) in enumerate(robot.JOINT_LIMITS_DEG):
            if not lo <= target[i] <= hi:
                raise ValueError(f"{robot.JOINT_NAMES[i]} = {target[i]}° is outside its limit [{lo}, {hi}]")

        start = self.joints_deg.copy()
        biggest_move = np.max(np.abs(target - start))
        duration = max(biggest_move / (speed or self.speed), 0.1)
        steps = max(int(duration * FPS), 1)
        for k in range(1, steps + 1):
            s = k / steps
            s = 3 * s**2 - 2 * s**3  # smooth start and stop (ease in/out)
            self.joints_deg = start + (target - start) * s
            self._draw()
            plt.pause(1 / FPS)
        print(f"Reached joints {np.round(self.joints_deg).astype(int).tolist()}  ->  tool at {self.tool_position()}")

    def move_joint(self, joint_number, angle_deg, speed=None):
        """Move just one joint (1..6) to an angle, others stay still."""
        target = self.joints_deg.copy()
        target[joint_number - 1] = angle_deg
        self.move_joints(target, speed)

    def home(self):
        self.move_joints(HOME_DEG)

    def tool_position(self):
        """Tool tip [x, y, z] in metres."""
        frames = robot.forward_kinematics(np.radians(self.joints_deg))
        return np.round(frames[-1][:3, 3], 3).tolist()

    def wait(self, seconds):
        plt.pause(seconds)

    def clear_trail(self):
        self.trail = []

    def done(self):
        """Call at the end: keeps the window open until you close it."""
        print("Program finished. Close the window to exit.")
        plt.show()

    # ---------- drawing ----------

    def _draw(self):
        frames = robot.forward_kinematics(np.radians(self.joints_deg))
        self.trail.append(frames[-1][:3, 3])

        elev, azim = self.ax.elev, self.ax.azim
        self.ax.cla()
        robot.setup_axes(self.ax)
        if len(self.trail) > 1:
            t = np.array(self.trail)
            self.ax.plot(t[:, 0], t[:, 1], t[:, 2], ":", color="#e67e22", linewidth=1.5)
        robot.draw_robot(self.ax, frames)
        self.ax.view_init(elev, azim)

        j = " ".join(f"{a:5.0f}" for a in self.joints_deg)
        x, y, z = frames[-1][:3, 3]
        self.text.set_text(f"Joints(°): {j}    Tool: X={x:+.3f} Y={y:+.3f} Z={z:+.3f}")
