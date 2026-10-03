"""
6-axis arm used by each gantry "hand" - same UR5-style geometry as robot.py,
but it can be scaled up (an industrial-size version) and it can point the tool
in ANY direction, not only straight down.

All positions here are in the arm's own base frame (metres).
"""
import numpy as np

UR_A = [0.0, -0.425, -0.39225, 0.0, 0.0, 0.0]
UR_D = [0.089159, 0.0, 0.0, 0.10915, 0.09465, 0.0823]
UR_ALPHA = [np.pi / 2, 0.0, 0.0, np.pi / 2, -np.pi / 2, 0.0]


def dh_transform(a, d, alpha, theta):
    ct, st = np.cos(theta), np.sin(theta)
    ca, sa = np.cos(alpha), np.sin(alpha)
    return np.array([
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0.0,      sa,       ca,      d],
        [0.0,     0.0,      0.0,    1.0],
    ])


def wrap(angle):
    return (angle + np.pi) % (2 * np.pi) - np.pi


class Arm:
    """A UR5-shaped arm, `scale` times bigger, with a tool of `tool_length` metres."""

    def __init__(self, scale=1.0, tool_length=0.15, joint_speed_deg=120.0):
        self.a = np.array(UR_A) * scale
        self.d = np.array(UR_D) * scale
        self.alpha = np.array(UR_ALPHA)
        self.tool_length = tool_length
        self.joint_speed = np.radians(joint_speed_deg)
        self.reach = (abs(self.a[1]) + abs(self.a[2]) + self.d[4] + self.d[5]) + tool_length

    def frames(self, q):
        """Base, the 6 joint frames, then the tool tip (8 frames, 4x4 each)."""
        T = np.eye(4)
        out = [T]
        for i in range(6):
            T = T @ dh_transform(self.a[i], self.d[i], self.alpha[i], q[i])
            out.append(T)
        tip = T.copy()
        tip[:3, 3] = T[:3, 3] + T[:3, 2] * self.tool_length
        out.append(tip)
        return out

    def tip(self, q):
        """Tool tip position and the direction the tool points (its Z axis)."""
        T = self.frames(q)[-1]
        return T[:3, 3], T[:3, 2]

    def ik(self, target, direction, seed, iterations=80, pos_tol=5e-5, dir_tol=2e-4):
        """Joint angles that put the tool tip on `target`, pointing along `direction`.

        Damped least squares with the exact (geometric) Jacobian. Starts from `seed`
        and stays close to it, so a path solved point by point moves smoothly.
        Returns (q, position_error_m, direction_error_rad).
        """
        q = np.array(seed, dtype=float)
        target = np.asarray(target, dtype=float)
        d = np.asarray(direction, dtype=float)
        d = d / np.linalg.norm(d)
        w = 0.3  # 1 radian of pointing error "costs" the same as 0.3 m of position error
        for _ in range(iterations):
            F = self.frames(q)
            p, z = F[-1][:3, 3], F[-1][:3, 2]
            e_pos = target - p
            axis = np.cross(z, d)
            s, c = np.linalg.norm(axis), np.dot(z, d)
            angle = np.arctan2(s, c)
            if s > 1e-12:
                e_rot = axis / s * angle
            elif c < 0:  # pointing exactly backwards: turn about any sideways axis
                e_rot = np.cross(z, [1.0, 0, 0] if abs(z[0]) < 0.9 else [0, 1.0, 0])
                e_rot *= np.pi / np.linalg.norm(e_rot)
            else:
                e_rot = np.zeros(3)
            if np.linalg.norm(e_pos) < pos_tol and angle < dir_tol:
                break
            J = np.zeros((6, 6))
            for i in range(6):
                zi, oi = F[i][:3, 2], F[i][:3, 3]
                J[:3, i] = np.cross(zi, p - oi)
                J[3:, i] = zi
            P = np.eye(3) - np.outer(z, z)  # spinning around the torch axis doesn't matter
            J[3:] = w * (P @ J[3:])
            e = np.concatenate([e_pos, w * e_rot])
            damping = 0.02
            dq = J.T @ np.linalg.solve(J @ J.T + damping**2 * np.eye(6), e)
            biggest = np.max(np.abs(dq))
            if biggest > 0.3:
                dq *= 0.3 / biggest
            q = q + dq
        q = np.asarray(seed) + wrap(q - np.asarray(seed))  # nearest equivalent angles
        p, z = self.tip(q)
        return q, float(np.linalg.norm(target - p)), float(np.arccos(np.clip(np.dot(z, d), -1, 1)))
