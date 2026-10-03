"""
Solid shapes for the 3D view: boxes and 6-sided "tubes", as lists of flat faces,
with simple lighting so they look solid (faces turned towards the light are brighter).
"""
import matplotlib.colors
import numpy as np

LIGHT = np.array([0.35, -0.5, 0.8]) / np.linalg.norm([0.35, -0.5, 0.8])


def box(x0, x1, y0, y1, z0, z1):
    return [
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
        [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
    ]


def centred_box(c, size):
    c, h = np.asarray(c), np.asarray(size) / 2
    return box(c[0] - h[0], c[0] + h[0], c[1] - h[1], c[1] + h[1], c[2] - h[2], c[2] + h[2])


def tube(a, b, radius, sides=6, caps=True):
    """A prism from point a to point b - used for arm links and tools."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    axis = b - a
    length = np.linalg.norm(axis)
    if length < 1e-9:
        return []
    axis /= length
    helper = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(axis, helper)
    u /= np.linalg.norm(u)
    v = np.cross(axis, u)
    angles = np.linspace(0, 2 * np.pi, sides + 1)[:-1]
    ring = [radius * (np.cos(t) * u + np.sin(t) * v) for t in angles]
    faces = []
    for i in range(sides):
        j = (i + 1) % sides
        faces.append([a + ring[i], a + ring[j], b + ring[j], b + ring[i]])
    if caps:
        faces.append([a + r for r in ring[::-1]])
        faces.append([b + r for r in ring])
    return faces


def lit(faces, color):
    """Colour for each face, brighter when it faces the light."""
    if not faces:
        return []
    rgb = np.array(matplotlib.colors.to_rgb(color))
    tri = np.array([[f[0], f[1], f[2]] for f in faces], dtype=float)   # 3 corners are enough
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    k = np.where(norm < 1e-12, 0.75, 0.5 + 0.5 * np.abs(n @ LIGHT) / np.maximum(norm, 1e-12))
    return [tuple(c) for c in np.clip(k[:, None] * rgb, 0, 1)]
