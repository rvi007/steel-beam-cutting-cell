"""Random (but valid) jobs - used by the tests to try lots of layouts."""
import numpy as np

from gantry.beam import PROFILES, Job


def random_job(seed, n=14):
    rng = np.random.default_rng(seed)
    profile = list(PROFILES)[seed % len(PROFILES)]
    job = Job(profile, 12.0 if seed % 3 else 6.0)
    p = job.p
    tries = 0
    while len(job.features) < n and tries < 400:
        tries += 1
        kind = str(rng.choice(["hole", "hole", "slot", "cut", "notch"]))
        x = round(float(rng.uniform(0.05, job.length - 0.05)), 3)
        thick = max(p["tf"], p["tw"])
        d = round(float(rng.uniform(max(0.014, 1.25 * thick), 0.06)), 3)
        if kind in ("hole", "slot"):
            face = str(rng.choice(["top", "web"]))
            if face == "top":
                v = float(rng.choice([-1, 1]) * rng.uniform(p["tw"] / 2 + 0.02, p["b"] / 2 - 0.01))
            else:
                v = float(rng.uniform(p["tf"] + 0.02, p["h"] - p["tf"] - 0.02))
            f = {"type": kind, "face": str(face), "x": x, "v": round(v, 3), "d": d}
            if kind == "slot":
                f["len"] = round(d + float(rng.uniform(0.01, 0.06)), 3)
        elif kind == "cut":
            f = {"type": "cut", "x": x}
        else:
            ends = [0.0] + job.cuts() + [job.length]
            end = ends[int(rng.integers(len(ends)))]
            side = 1 if end == 0.0 else -1 if end == job.length else int(rng.choice([-1, 1]))
            f = {"type": "notch", "x": end, "side": side, "w": round(float(rng.uniform(0.05, 0.15)), 3),
                 "depth": round(float(rng.uniform(p["tf"] + 0.02, p["h"] / 2)), 3)}
        job.features.append(f)
        if job.problems():          # this feature, or it broke an earlier one
            job.features.pop()
    return job
