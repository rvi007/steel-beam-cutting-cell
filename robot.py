"""
A simple 6-axis robot arm model (geometry similar to a Universal Robots UR5).

Everything here uses only numpy + matplotlib, so it runs fully offline.
Lessons import this file and build on it step by step.
"""
import numpy as np

# Denavit-Hartenberg (DH) parameters, one row per joint:
#   a     = link length   (metres)
#   d     = link offset   (metres)
#   alpha = link twist    (radians)
# Joint angles (theta) are what we control.
DH_A = [0.0, -0.425, -0.39225, 0.0, 0.0, 0.0]
DH_D = [0.089159, 0.0, 0.0, 0.10915, 0.09465, 0.0823]
DH_ALPHA = [np.pi / 2, 0.0, 0.0, np.pi / 2, -np.pi / 2, 0.0]

JOINT_NAMES = ["J1 Base", "J2 Shoulder", "J3 Elbow", "J4 Wrist 1", "J5 Wrist 2", "J6 Wrist 3"]
JOINT_LIMITS_DEG = [(-180, 180)] * 6


def dh_transform(a, d, alpha, theta):
    """4x4 transform from one joint frame to the next (standard DH)."""
    ct, st = np.cos(theta), np.sin(theta)
    ca, sa = np.cos(alpha), np.sin(alpha)
    return np.array([
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0.0,      sa,       ca,      d],
        [0.0,     0.0,      0.0,    1.0],
    ])


def forward_kinematics(joint_angles_rad):
    """Return the list of 4x4 frames: base, then after each of the 6 joints.

    The last frame is the tool (end-effector) pose.
    """
    T = np.eye(4)
    frames = [T]
    for i in range(6):
        T = T @ dh_transform(DH_A[i], DH_D[i], DH_ALPHA[i], joint_angles_rad[i])
        frames.append(T)
    return frames


def draw_robot(ax, frames, show_frames=True):
    """Draw the arm as lines + joint dots on a matplotlib 3D axis."""
    pts = np.array([F[:3, 3] for F in frames])
    ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], "-", color="#4a6fa5", linewidth=5)
    ax.scatter(pts[:-1, 0], pts[:-1, 1], pts[:-1, 2], color="#333333", s=40)
    ax.scatter(*pts[-1], color="#d9534f", s=80)  # tool tip in red

    if show_frames:  # small x/y/z arrows at the tool: red/green/blue
        tool = frames[-1]
        origin = tool[:3, 3]
        for axis, color in zip(range(3), ["r", "g", "b"]):
            direction = tool[:3, axis] * 0.08
            ax.quiver(*origin, *direction, color=color, linewidth=2)


def setup_axes(ax, reach=0.9):
    ax.set_xlim(-reach, reach)
    ax.set_ylim(-reach, reach)
    ax.set_zlim(-0.2, reach)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")
    ax.set_box_aspect((2 * reach, 2 * reach, reach + 0.2))


def inverse_kinematics(target_xyz, seed_rad, tool_down=True, iterations=100, tol=1e-4):
    """Find joint angles that put the tool tip at target_xyz (metres).

    Numerical method (damped least squares), the same idea real robot software uses:
      1. Measure the error: where the tool is vs. where we want it.
      2. Use the Jacobian (how much each joint moves the tool) to pick a small
         joint change that shrinks the error.
      3. Repeat until the error is tiny.
    With tool_down=True it also keeps the tool's Z axis pointing straight down,
    like a gripper reaching for something on a table.

    Starts from seed_rad (usually the current pose), so the arm moves smoothly.
    Returns (joint_angles_rad, position_error_m).
    """
    q = np.array(seed_rad, dtype=float)
    target = np.asarray(target_xyz, dtype=float)
    down = np.array([0.0, 0.0, -1.0])

    def error(q):
        T = forward_kinematics(q)[-1]
        e = target - T[:3, 3]
        if tool_down:
            e = np.concatenate([e, np.cross(T[:3, 2], down)])  # tilt error
        return e

    damping = 0.01
    for _ in range(iterations):
        e = error(q)
        if np.linalg.norm(e) < tol:
            break
        # Jacobian by "wiggling" each joint a tiny bit and seeing how the error changes
        J = np.zeros((len(e), 6))
        h = 1e-6
        for i in range(6):
            dq = np.zeros(6)
            dq[i] = h
            J[:, i] = (e - error(q + dq)) / h
        step = J.T @ np.linalg.solve(J @ J.T + damping**2 * np.eye(len(e)), e)
        q = q + np.clip(step, -0.2, 0.2)  # small steps keep it stable
        q = (q + np.pi) % (2 * np.pi) - np.pi  # keep angles in -180..180

    pos_err = np.linalg.norm(target - forward_kinematics(q)[-1][:3, 3])
    return q, pos_err
