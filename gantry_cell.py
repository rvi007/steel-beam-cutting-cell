"""
GANTRY CELL - a 12 m steel-beam cutting cell with TWO robot hands.

Run:   python3 gantry_cell.py

The machine (see GANTRY.md for the full plan):
  - 12 m x 3 m work area, overhead rails at 3.4 m.
  - Two bridges on the same rails, each with a carriage, a drop column and a
    6-axis arm hanging upside down:
        CUTTER  (red)  - plasma torch: holes, slots, notches (copes), cut to length
        HANDLER (blue) - magnet gripper: holds each part while it is cut free,
                         then carries it to the outfeed rack.

How to use it:
  1. Pick a tool on the right (Hole, Slot, Notch, Cut, Delete) and a size.
  2. CLICK on the beam layout - the TOP FLANGE strip or the WEB strip - to place it.
       Hole / Slot : click where the centre goes.
       Notch       : click just inside a part end (beam end or a cut).
       Cut         : click where the beam should be cut.
       Delete      : click on a feature to remove it.
     Scroll the mouse wheel on a strip to zoom in, right-click to zoom out.
  3. Press PLAN. The planner works out every move for both hands, keeps the bridges
     apart and checks the arms never touch the steel.
  4. Press RUN. Drag the Time slider to jump around, use Speed to go faster.
     Switch View to follow the Cutter or the Handler close up.

Arduino (optional): the servo shows where the Cutter's bridge is along the 12 m
(0 deg = start, 180 deg = far end) and the knob sets the playback speed.
"""
import glob
import os
import time

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, Rectangle
from matplotlib.widgets import Button, RadioButtons, Slider
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from gantry import shapes
from gantry.beam import PROFILES, Job, demo_job
from gantry.check import check_plan
from gantry.machine import BEAM_Y, BED_Z, OUTFEED_Y, RAIL_Z, WIDTH, X_LIMITS, make_hands
from gantry.planner import Plan

JOB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_job.json")
SNAP = 0.005                       # clicks snap to 5 mm
STEEL = "#8d959e"
DONE = "#58b07a"
HANDS = make_hands()            # used to draw the hands before there is a plan
VIEWS = ["Whole cell", "Follow Cutter", "Follow Handler", "From above"]


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
state = {"job": demo_job(), "plan": None, "t": 0.0, "running": False, "speed": 10.0,
         "view": VIEWS[0], "message": "Demo job loaded. Press PLAN, then RUN.", "msg_bad": False,
         "zoom": [0.0, 12.0], "last_real": time.monotonic(), "knob": None, "buffer": "",
         "last_sent": None, "checked": "", "ticking": False}

# ------------------------------------------------------------------ figure layout
fig = plt.figure("Gantry cell - 12 m beam cutting with two robot hands", figsize=(15, 9))
ax = fig.add_axes([0.0, 0.24, 0.60, 0.76], projection="3d")
ax_top = fig.add_axes([0.645, 0.815, 0.34, 0.12])
ax_web = fig.add_axes([0.645, 0.625, 0.34, 0.12])
ax_status = fig.add_axes([0.0, 0.0, 0.6, 0.19])
ax_status.set_xticks([])           # an empty panel WITH a background, so redrawing it
ax_status.set_yticks([])           # wipes the old text
for spine in ax_status.spines.values():
    spine.set_visible(False)
status = ax_status.text(0.015, 0.08, "", family="monospace", fontsize=8.5, va="bottom",
                        transform=ax_status.transAxes)
info = fig.text(0.645, 0.015, "", family="monospace", fontsize=8.5, va="bottom")

fig.text(0.645, 0.965, "BEAM LAYOUT - click to place features", fontsize=11, weight="bold")
tool_radio = RadioButtons(fig.add_axes([0.645, 0.37, 0.085, 0.2]),
                          ["Hole", "Slot", "Notch", "Cut", "Delete"])
profile_radio = RadioButtons(fig.add_axes([0.735, 0.37, 0.085, 0.2]), list(PROFILES), active=1)
stock_radio = RadioButtons(fig.add_axes([0.825, 0.47, 0.07, 0.10]), ["12 m", "6 m"])
view_radio = RadioButtons(fig.add_axes([0.825, 0.37, 0.16, 0.095]), VIEWS)
for title, x in (("Tool", 0.645), ("Profile", 0.735), ("Stock", 0.825)):
    fig.text(x, 0.575, title, fontsize=9, weight="bold")

size = Slider(fig.add_axes([0.70, 0.325, 0.22, 0.022]), "Size mm", 10, 200, valinit=22, valstep=1)
extra = Slider(fig.add_axes([0.70, 0.295, 0.22, 0.022]), "Slot len / depth", 20, 250, valinit=45, valstep=1)
speed = Slider(fig.add_axes([0.70, 0.265, 0.22, 0.022]), "Speed x", 1, 60, valinit=10, valstep=1)
timeline = Slider(fig.add_axes([0.06, 0.205, 0.50, 0.022]), "Time s", 0, 1, valinit=0)
timeline.drawon = False       # redrawn by frame() itself - much faster than a full redraw

buttons = {}
for i, name in enumerate(["Demo", "Clear", "Undo", "PLAN", "RUN", "Save", "Load"]):
    buttons[name] = Button(fig.add_axes([0.645 + i * 0.049, 0.215, 0.046, 0.035]), name)
buttons["PLAN"].color = "#f5cba7"
buttons["RUN"].color = "#abebc6"
ax.view_init(24, -62)
ax.set_axis_off()               # no grid: it's slow to draw, and the floor shows the scale
ax.computed_zorder = False      # we set the drawing order ourselves (floor, lines, solids)
FAST = {"background": None, "frames": 0, "done": -1}
# matplotlib before 3.6 (the Jetson's 3.5) puts the 3D camera closer: zoom out a bit there
ZOOM = 0.95 if tuple(int(n) for n in matplotlib.__version__.split(".")[:2]) < (3, 6) else 1.25


# ------------------------------------------------------------------ helpers
def snap(v):
    return round(v / SNAP) * SNAP


def joined(segments):
    """Many polylines -> one x, y, z list with gaps (NaN) between them."""
    xs, ys, zs = [], [], []
    for seg in segments:
        seg = np.asarray(seg, float)
        xs += list(seg[:, 0]) + [np.nan]
        ys += list(seg[:, 1]) + [np.nan]
        zs += list(seg[:, 2]) + [np.nan]
    return np.array(xs), np.array(ys), np.array(zs)


# ------------------------------------------------------------------ 3D scene
artists = {}
STATIC = []                     # rails and posts as (box, colour): solid, but never move
VIEW_BOX = {"limits": None}     # in close-up views, boxes are trimmed to this


def clipped_box(x0, x1, y0, y1, z0, z1):
    """A solid box, trimmed to the close-up view (matplotlib doesn't trim 3D shapes itself)."""
    lim = VIEW_BOX["limits"]
    if lim is not None:
        (ax0, ax1), (ay0, ay1), (az0, az1) = lim
        x0, x1 = max(x0, ax0), min(x1, ax1)
        y0, y1 = max(y0, ay0), min(y1, ay1)
        z0, z1 = max(z0, az0), min(z1, az1)
        if x0 >= x1 or y0 >= y1 or z0 >= z1:
            return []
    return shapes.box(x0, x1, y0, y1, z0, z1)


def build_scene():
    """Draw everything that doesn't move, and create the moving parts once."""
    ax.cla()
    artists["labels"] = []
    ax.set_axis_off()            # cla() turns the (slow) axis grid back on
    ax.computed_zorder = False
    L = state["job"].length
    xa, xb = X_LIMITS
    STATIC.clear()
    for y in (-WIDTH / 2, WIDTH / 2):                         # rails on posts
        STATIC.append(((xa, xb, y - 0.08, y + 0.08, RAIL_Z - 0.12, RAIL_Z + 0.04), "#5d6d7e"))
        for x in np.linspace(xa, xb, 5):                       # yellow safety-painted posts
            STATIC.append(((x - 0.08, x + 0.08, y - 0.08, y + 0.08, 0, RAIL_Z - 0.12), "#f4d03f"))
    floor = Poly3DCollection([[(xa, -WIDTH / 2 - 0.2, 0), (xb, -WIDTH / 2 - 0.2, 0),
                               (xb, WIDTH / 2 + 0.2, 0), (xa, WIDTH / 2 + 0.2, 0)]],
                             facecolors="#e8e8e4", edgecolors="none", zorder=0)
    ax.add_collection3d(floor)
    grid, legs, tops, rack_legs, rack_tops = [], [], [], [], []
    for x in range(int(np.ceil(xa)), int(xb) + 1):             # 1 m floor grid
        grid.append([(x, -WIDTH / 2 - 0.2, 0), (x, WIDTH / 2 + 0.2, 0)])
        if x % 2 == 0 and 0 <= x <= L:
            artists.setdefault("labels", []).append(
                ax.text(x, -WIDTH / 2 - 0.45, 0, f"{x} m", fontsize=7, color="#777777", zorder=1))
    # beam bed (roller supports every metre) and outfeed rack
    for x in np.arange(0, L + 0.01, 1.0):
        tops.append([(x, BEAM_Y - 0.25, BED_Z), (x, BEAM_Y + 0.25, BED_Z)])
        legs.append([(x, BEAM_Y, 0), (x, BEAM_Y, BED_Z)])
        rack_tops.append([(x, OUTFEED_Y - 0.3, BED_Z), (x, OUTFEED_Y + 0.3, BED_Z)])
        rack_legs.append([(x, OUTFEED_Y, 0), (x, OUTFEED_Y, BED_Z)])
    rack_tops.append([(0, OUTFEED_Y, BED_Z), (L, OUTFEED_Y, BED_Z)])
    # one line object per group (with gaps) is much faster to draw than many lines
    for segs, color, width, z in ((grid, "#d0d0cc", 0.6, 1), (legs, "#6e4b2a", 1.5, 2),
                                  (tops, "#6e4b2a", 3, 2), (rack_legs, "#1e8449", 1.5, 2),
                                  (rack_tops, "#1e8449", 3, 2)):
        xs, ys, zs = joined(segs)
        ax.plot(xs, ys, zs, color=color, linewidth=width, zorder=z)

    artists["solids"] = Poly3DCollection([], linewidths=0.25, edgecolors=(0.15, 0.15, 0.15, 0.35), zorder=3)
    ax.add_collection3d(artists["solids"])
    artists["kerf"] = ax.plot([], [], [], color="#1c1c1c", linewidth=1.6, zorder=4)[0]
    artists["flame"] = ax.plot([], [], [], color="#ff8c00", linewidth=3, zorder=5)[0]
    artists["sparks"] = ax.scatter([], [], [], color="#ffcc00", s=4, zorder=5)


def hand_solids(hand, g, q, color):
    """Bridge, carriage, column, arm and tool of one hand as solid faces."""
    faces, colors = [], []

    def add(f, c):
        faces.extend(f)
        colors.extend(shapes.lit(f, c))

    add(clipped_box(g[0] - 0.14, g[0] + 0.14, -WIDTH / 2, WIDTH / 2, RAIL_Z + 0.04, RAIL_Z + 0.34), "#566573")
    add(clipped_box(g[0] - 0.21, g[0] + 0.21, g[1] - 0.2, g[1] + 0.2, RAIL_Z - 0.14, RAIL_Z + 0.06), color)
    add(clipped_box(g[0] - 0.08, g[0] + 0.08, g[1] - 0.08, g[1] + 0.08, g[2] + 0.05, RAIL_Z - 0.14), color)
    pts = np.array([F[:3, 3] for F in hand.world_frames(g, q)])
    r = 0.045 * hand.arm.reach / 1.0
    add(shapes.tube(pts[0] + [0, 0, 0.06], pts[1], r * 1.4), "#34495e")      # base / shoulder housing
    for i in range(1, 6):
        add(shapes.tube(pts[i], pts[i + 1], r * (1.0 if i < 3 else 0.75)), color if i % 2 else "#ecf0f1")
    if hand.tool == "torch":
        add(shapes.tube(pts[6], pts[7], 0.018), "#1c1c1c")
    else:
        d = pts[7] - pts[6]
        d /= np.linalg.norm(d)
        add(shapes.tube(pts[6], pts[7] - d * 0.03, 0.03), "#5d6d7e")
        add(shapes.tube(pts[7] - d * 0.03, pts[7], 0.09, sides=8), "#922b21")   # magnet pad
    return faces, colors


def set_view():
    plan, t = state["plan"], state["t"]
    view = state["view"]
    if view in ("Follow Cutter", "Follow Handler") and plan is not None:
        track = plan.tc if view == "Follow Cutter" else plan.th
        g, q = track.at(t)
        c, _ = track.hand.tip(g, q)
        r = 0.8 if view == "Follow Cutter" else 1.3
        lim = ((c[0] - r, c[0] + r), (c[1] - r, c[1] + r), (c[2] - r * 0.6, c[2] + r * 1.4))
        VIEW_BOX["limits"] = lim
        for label in artists["labels"]:      # 3D text isn't trimmed to the view: hide it
            label.set_visible(False)
        ax.set_xlim(*lim[0])
        ax.set_ylim(*lim[1])
        ax.set_zlim(*lim[2])
        aspect = (1, 1, 1)
    else:
        VIEW_BOX["limits"] = None
        for label in artists["labels"]:
            label.set_visible(True)
        ax.set_xlim(*X_LIMITS)
        ax.set_ylim(-WIDTH / 2 - 0.1, WIDTH / 2 + 0.1)
        ax.set_zlim(0, RAIL_Z + 0.4)
        aspect = (X_LIMITS[1] - X_LIMITS[0], WIDTH + 0.2, RAIL_Z + 0.4)
    ax.set_box_aspect(aspect, zoom=ZOOM)


def draw_3d():
    job, plan, t = state["job"], state["plan"], state["t"]
    set_view()
    faces, colors = [], []
    for b, color in STATIC:
        f = clipped_box(*b)
        faces += f
        colors += shapes.lit(f, color)
    # beam parts (moved by the Handler once they are cut free)
    for part in range(len(job.parts())):
        off = plan.part_offset(part, t) if plan else np.zeros(3)
        moved = np.linalg.norm(off) > 1e-6
        for b in job.part_boxes(part):
            f = clipped_box(b[0] + off[0], b[1] + off[0], b[2] + off[1], b[3] + off[1],
                            b[4] + off[2], b[5] + off[2])
            faces += f
            colors += shapes.lit(f, DONE if moved else STEEL)

    # the two hands
    tips = {}
    for k, name in enumerate(("Cutter", "Handler")):
        if plan:
            track = plan.tc if name == "Cutter" else plan.th
            hand = track.hand
            g, q = track.at(t)
        else:
            hand = HANDS[k]
            g, q = hand.park, hand.preference([0, 0, -1], [1, 0, 0] if k == 0 else [-1, 0, 0])[1]
        f, c = hand_solids(hand, g, q, hand.color)
        faces += f
        colors += c
        tips[name] = hand.world_frames(g, q)[-1]
    artists["solids"].set_verts(faces)
    artists["solids"].set_facecolor(colors)

    # kerfs: what the torch has cut so far (they travel with their part)
    kerfs = []
    flame_on = False
    if plan:
        for c in plan.cuts:
            n = int(np.searchsorted(c["times"], t, side="right"))
            if n < 2:
                continue
            off = plan.part_offset(job.part_of(job.features[c["feature"]]), t)
            kerfs.append(c["points"][:n] + off)
        flame_on = any(c["t_on"] <= t <= c["times"][-1] for c in plan.cuts)
    xs, ys, zs = joined(kerfs)
    if VIEW_BOX["limits"] is not None:          # hide kerf outside the close-up
        (x0, x1), (y0, y1), (z0, z1) = VIEW_BOX["limits"]
        out = (xs < x0) | (xs > x1) | (ys < y0) | (ys > y1) | (zs < z0) | (zs > z1)
        xs, ys, zs = (np.where(out, np.nan, a) for a in (xs, ys, zs))
    artists["kerf"].set_data_3d(xs, ys, zs)
    tip, d = tips["Cutter"][:3, 3], tips["Cutter"][:3, 2]
    if flame_on:
        end = tip + d * 0.03
        artists["flame"].set_data_3d(*np.array([tip, end]).T)
        rng = np.random.default_rng(int(t * 10))
        sp = tip + d * 0.02 + rng.normal(0, 1, (25, 3)) * [0.03, 0.03, 0.02] + [0, 0, -0.05]
        artists["sparks"]._offsets3d = (sp[:, 0], sp[:, 1], sp[:, 2])
    else:
        artists["flame"].set_data_3d(np.array([]), np.array([]), np.array([]))
        artists["sparks"]._offsets3d = ([], [], [])


# ------------------------------------------------------------------ 2D layout
def draw_layout():
    job, plan, t = state["job"], state["plan"], state["t"]
    p = job.p
    x0, x1 = state["zoom"]
    for a, label, lo, hi in ((ax_top, "TOP FLANGE (seen from above)  v = sideways mm", -p["b"] / 2, p["b"] / 2),
                             (ax_web, "WEB (seen from +Y side)  v = height mm", 0, p["h"])):
        a.cla()
        a.set_xlim(x0, x1)
        a.set_ylim(lo * 1000 - 5, hi * 1000 + 5)
        a.set_title(label, fontsize=8.5, loc="left")
        a.tick_params(labelsize=7)
        a.add_patch(Rectangle((0, lo * 1000), job.length, (hi - lo) * 1000, color="#d5d8dc"))
    # web position on the top flange, flanges on the web view
    ax_top.add_patch(Rectangle((0, -p["tw"] / 2 * 1000), job.length, p["tw"] * 1000, color="#aab0b6"))
    for z in (0, p["h"] - p["tf"]):
        ax_web.add_patch(Rectangle((0, z * 1000), job.length, p["tf"] * 1000, color="#aab0b6"))

    done = plan.feature_done if plan else {}
    for i, f in enumerate(job.features):
        bad = job.check(f)
        finished = i in done and done[i] <= t
        color = "#d62728" if bad else (DONE if finished else "#1f4e8c")
        if f["type"] in ("hole", "slot"):
            a = ax_top if f["face"] == "top" else ax_web
            v = f["v"] * 1000
            length = f.get("len", f["d"])
            if f["type"] == "hole":
                a.add_patch(Ellipse((f["x"], v), length, f["d"] * 1000, color=color, alpha=0.6))
            else:
                a.add_patch(Rectangle((f["x"] - length / 2, v - f["d"] * 500), length, f["d"] * 1000,
                                      color=color, alpha=0.6))
            a.plot([f["x"]], [v], "o" if f["type"] == "hole" else "s", color=color, markersize=4)
        elif f["type"] == "notch":
            xs = sorted([f["x"], f["x"] + f["side"] * f["w"]])
            ax_top.add_patch(Rectangle((xs[0], -p["b"] * 500), xs[1] - xs[0], p["b"] * 1000,
                                       color=color, alpha=0.45))
            ax_web.add_patch(Rectangle((xs[0], (p["h"] - f["depth"]) * 1000), xs[1] - xs[0],
                                       f["depth"] * 1000, color=color, alpha=0.45))
        elif f["type"] == "cut":
            for a in (ax_top, ax_web):
                a.axvline(f["x"], color="#d62728" if bad else ("#117a65" if finished else "#c0392b"),
                          linewidth=2)
    # part labels
    for i, (a, b) in enumerate(job.parts()):
        mid = (a + b) / 2
        if x0 <= mid <= x1 and (b - a) / (x1 - x0) > 0.09:
            ax_web.text(mid, p["h"] * 500, f"P{i + 1}\n{b - a:.2f} m\n{job.weight(i):.0f} kg",
                        ha="center", va="center", fontsize=6.5, color="#333333", linespacing=1.0)
    if plan:
        g, _ = plan.tc.at(t)
        for a in (ax_top, ax_web):
            a.axvline(np.clip(g[0], 0, job.length), color="#c0392b", linestyle=":", linewidth=1)


# ------------------------------------------------------------------ text panels
def draw_text():
    plan, t = state["plan"], state["t"]
    lines = []
    if plan:
        lines.append(f"t = {t:6.1f} s / {plan.duration:.0f} s   {'RUNNING' if state['running'] else 'paused'}"
                     f"   x{state['speed']:.0f}")
        lines.append("CUTTER : " + plan.step_at(t, "Cutter"))
        lines.append("HANDLER: " + plan.step_at(t, "Handler"))
        for track in (plan.tc, plan.th):
            g, q = track.at(t)
            lines.append(f"{track.hand.name:<8} X{g[0]:7.3f} Y{g[1]:+6.3f} Z{g[2]:6.3f} m | J "
                         + " ".join(f"{np.degrees(a):+5.0f}" for a in q))
    else:
        lines.append("No plan yet - press PLAN.")
    lines.append(state["message"])
    status.set_text("\n".join(lines))
    status.set_color("#b03a2e" if state["msg_bad"] else "#000000")


def draw_info():
    job, plan = state["job"], state["plan"]
    rows = [f"JOB  {job.profile}  stock {job.length:.0f} m  ({job.p['kg_m']} kg/m)",
            f"     {len(job.features)} features, {len(job.parts())} pieces"]
    if plan:
        rows += ["PLAN " + line for line in plan.summary().split("\n")]
        rows.append(f"     closest bridges {plan.min_gap():.2f} m   {state['checked']}")
        for w in plan.warnings[:3]:
            rows.append("  ! " + w)
    problems = job.problems()
    for prob in problems[:3]:
        rows.append("  x " + prob)
    info.set_text("\n".join(rows))


def redraw():
    """Full redraw - after an edit, a new plan, a view change..."""
    draw_3d()
    draw_layout()
    draw_text()
    draw_info()
    FAST["background"] = None
    fig.canvas.draw_idle()


def frame():
    """Fast redraw while the job runs: only the 3D view, the status text and the time
    slider are drawn again ("blitting"); the layout strips every second or so."""
    canvas = fig.canvas
    if FAST["background"] is None:          # first frame after a full redraw
        draw_3d()
        draw_layout()
        draw_text()
        canvas.draw()
        FAST["background"] = True
        return
    draw_3d()
    draw_text()
    r = canvas.get_renderer()
    redo = [ax, ax_status, timeline.ax]
    done = sum(1 for v in state["plan"].feature_done.values() if v <= state["t"])
    FAST["frames"] += 1
    if done != FAST["done"] or FAST["frames"] % 20 == 0:
        FAST["done"] = done
        draw_layout()
        redo += [ax_top, ax_web]
    for a in redo:
        a.draw(r)
        canvas.blit(a.bbox)
    canvas.flush_events()
    fig.stale = False


# ------------------------------------------------------------------ editing
def say(msg, bad=False):
    state["message"] = msg
    state["msg_bad"] = bad


def changed():
    state["plan"] = None
    state["running"] = False
    state["t"] = 0.0
    state["checked"] = ""


def add_feature(f):
    job = state["job"]
    msg = job.check(f)
    if msg:
        say(f"Can't add {f['type']}: {msg}", bad=True)
        return
    before = len(job.problems())
    job.features.append(f)
    if len(job.problems()) > before:          # it would spoil a feature that was fine
        job.features.pop()
        say(f"Can't add {f['type']} there: it clashes with another feature", bad=True)
        return
    changed()
    say(f"Added {f['type']} at x = {f['x']:.3f} m. Press PLAN when ready.")


def on_click(event):
    if event.inaxes is None:
        return
    a = event.inaxes
    if a not in (ax_top, ax_web):
        return
    if event.button == 3:                     # right click: zoom out fully
        state["zoom"] = [0.0, state["job"].length]
        redraw()
        return
    if event.button != 1 or event.xdata is None:
        return
    job = state["job"]
    x, v = snap(event.xdata), snap(event.ydata / 1000)
    face = "top" if a is ax_top else "web"
    tool = tool_radio.value_selected
    d = size.val / 1000
    if tool == "Hole":
        add_feature({"type": "hole", "face": face, "x": x, "v": v, "d": d})
    elif tool == "Slot":
        add_feature({"type": "slot", "face": face, "x": x, "v": v, "d": d,
                     "len": max(extra.val / 1000, d + 0.005)})
    elif tool == "Cut":
        add_feature({"type": "cut", "x": x})
    elif tool == "Notch":
        ends = [0.0] + job.cuts() + [job.length]
        end = min(ends, key=lambda e: abs(e - x))
        side = 1 if x >= end else -1
        if end == 0.0:
            side = 1
        if end == job.length:
            side = -1
        add_feature({"type": "notch", "x": end, "side": side, "w": d,
                     "depth": min(extra.val / 1000, job.p["h"] - job.p["tf"] - 0.02)})
    elif tool == "Delete":
        best, dist = None, 1e9
        span = state["zoom"][1] - state["zoom"][0]
        for i, f in enumerate(job.features):
            if f["type"] in ("hole", "slot") and f["face"] != face:
                continue
            fx = f["x"] + (f["side"] * f["w"] / 2 if f["type"] == "notch" else 0)
            dd = abs(fx - event.xdata)
            if f["type"] in ("hole", "slot"):
                dd += abs(f["v"] * 1000 - event.ydata) / 1000 * span / 3
            if dd < dist:
                best, dist = i, dd
        if best is not None and dist < span * 0.03:
            f = job.features.pop(best)
            changed()
            say(f"Deleted {f['type']} at x = {f['x']:.3f} m")
        else:
            say("Nothing close enough to delete - zoom in (mouse wheel) and click on it", bad=True)
    redraw()


def on_scroll(event):
    if event.inaxes not in (ax_top, ax_web) or event.xdata is None:
        return
    x0, x1 = state["zoom"]
    k = 0.6 if event.button == "up" else 1 / 0.6
    span = min(max((x1 - x0) * k, 0.2), state["job"].length)
    c = event.xdata
    x0 = np.clip(c - (c - x0) * span / (x1 - x0), 0, state["job"].length - span)
    state["zoom"] = [x0, x0 + span]
    draw_layout()
    fig.canvas.draw_idle()


def on_plan(_=None):
    job = state["job"]
    say("Planning both hands... (a few seconds)")
    draw_text()
    fig.canvas.draw_idle()
    plt.pause(0.01)
    t0 = time.monotonic()
    try:
        plan = Plan(job).build()
    except RuntimeError as e:
        say(f"Planning failed: {e}", bad=True)
        redraw()
        return
    state["plan"] = plan
    state["t"] = 0.0
    timeline.valmax = plan.duration
    timeline.ax.set_xlim(0, plan.duration)
    timeline.set_val(0.0)
    hits = check_plan(plan, step=0.5)
    state["checked"] = "collision check: OK" if not hits else f"COLLISIONS: {len(hits)}"
    skipped = len(job.problems())
    say(f"Planned in {time.monotonic() - t0:.1f} s. Press RUN."
        + (f"  ({skipped} feature(s) with problems were skipped)" if skipped else ""), bad=bool(hits))
    redraw()


def on_run(_=None):
    if state["plan"] is None:
        on_plan()
    if state["plan"] is None:
        return
    if state["t"] >= state["plan"].duration - 1e-6:
        state["t"] = 0.0
    state["running"] = not state["running"]
    state["last_real"] = time.monotonic()
    buttons["RUN"].label.set_text("PAUSE" if state["running"] else "RUN")
    redraw()


def on_time(val):
    if state["ticking"]:
        return
    if state["plan"] is not None:
        state["t"] = val
    redraw()


def set_job(job, msg):
    state["job"] = job
    state["zoom"] = [0.0, job.length]
    profile_radio.set_active(list(PROFILES).index(job.profile))
    stock_radio.set_active(0 if job.length > 6 else 1)
    changed()
    build_scene()
    say(msg)
    redraw()


def on_profile(label):
    if label != state["job"].profile:
        state["job"].profile = label
        changed()
        bad = len(state["job"].problems())
        say(f"Profile {label}." + (f" {bad} feature(s) don't fit any more (red)." if bad else ""), bad=bool(bad))
        redraw()


def on_stock(label):
    length = 12.0 if label.startswith("12") else 6.0
    if length != state["job"].length:
        state["job"].length = length
        state["zoom"] = [0.0, length]
        changed()
        build_scene()
        say(f"Stock length {length:.0f} m")
        redraw()


def on_view(label):
    state["view"] = label
    if label == "From above":
        ax.view_init(89, -90)
    elif label == "Whole cell":
        ax.view_init(24, -62)
    else:
        ax.view_init(28, -50)
    redraw()


def on_save(_=None):
    with open(JOB_FILE, "w") as fh:
        fh.write(state["job"].to_json())
    say(f"Saved to {os.path.basename(JOB_FILE)}")
    redraw()


def on_load(_=None):
    try:
        with open(JOB_FILE) as fh:
            set_job(Job.from_json(fh.read()), f"Loaded {os.path.basename(JOB_FILE)}")
    except (OSError, ValueError, KeyError) as e:
        say(f"Could not load {os.path.basename(JOB_FILE)}: {e}", bad=True)
        redraw()


def on_undo(_=None):
    if state["job"].features:
        f = state["job"].features.pop()
        changed()
        say(f"Removed the last {f['type']}")
    redraw()


fig.canvas.mpl_connect("button_press_event", on_click)
fig.canvas.mpl_connect("scroll_event", on_scroll)
buttons["Demo"].on_clicked(lambda _: set_job(demo_job(), "Demo job loaded. Press PLAN, then RUN."))
buttons["Clear"].on_clicked(lambda _: set_job(Job(state["job"].profile, state["job"].length),
                                              "Empty beam. Click on the layout to add features."))
buttons["Undo"].on_clicked(on_undo)
buttons["PLAN"].on_clicked(on_plan)
buttons["RUN"].on_clicked(on_run)
buttons["Save"].on_clicked(on_save)
buttons["Load"].on_clicked(on_load)
profile_radio.on_clicked(on_profile)
stock_radio.on_clicked(on_stock)
view_radio.on_clicked(on_view)
speed.on_changed(lambda v: state.update(speed=v))
timeline.on_changed(on_time)


def tick():
    """Advance the simulation clock (called about 20 times a second)."""
    now = time.monotonic()
    dt = min(now - state["last_real"], 0.25)
    state["last_real"] = now
    plan = state["plan"]
    if state["running"] and plan is not None:
        state["t"] = min(state["t"] + dt * state["speed"], plan.duration)
        if state["t"] >= plan.duration:
            state["running"] = False
            buttons["RUN"].label.set_text("RUN")
        state["ticking"] = True
        timeline.set_val(state["t"])
        state["ticking"] = False
        frame()


def arduino_io():
    if not arduino:
        return
    state["buffer"] += arduino.read(arduino.in_waiting or 1).decode(errors="ignore")
    *lines, state["buffer"] = state["buffer"].split("\n")
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("K") and ln[1:].isdigit():
            knob = int(ln[1:])
            if state["knob"] is None or abs(knob - state["knob"]) >= 3:
                state["knob"] = knob
                speed.set_val(int(round(1 + knob / 180 * 59)))
    if state["plan"] is not None:
        g, _ = state["plan"].tc.at(state["t"])
        servo = int(round(np.clip(g[0] / state["job"].length, 0, 1) * 180))
        if servo != state["last_sent"]:
            arduino.write(f"S{servo}\n".encode())
            state["last_sent"] = servo


build_scene()
redraw()

# Main loop: about 20 updates per second
plt.show(block=False)
while plt.fignum_exists(fig.number):
    arduino_io()
    tick()
    fig.canvas.start_event_loop(0.05)

if arduino:
    arduino.close()
