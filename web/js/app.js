// Beam Cell - the app: job state, tabs, planning and playback of the machine.
import * as THREE from "three";
import { get, post } from "./api.js";
import { CellScene } from "./scene.js";
import { trackAt } from "./kinematics.js";
import { MAT, partGroup, stockMesh, disposeGroup } from "./geometry.js";
import { initParts, renderPartList } from "./parts.js";
import { initLibrary } from "./library.js";
import { initCamera } from "./camera.js";
import { initHelp } from "./help.js";
import { initSafety, safety, connected, startMachine, stopMachine, jobFinished } from "./safety.js";
import { initManual, manual, manualPreview, planManual } from "./manual.js";

export const app = {
  info: null, sections: null, job: { stock_length: 12000, parts: [] }, bars: [], barIndex: 0,
  plan: null, t: 0, playing: false, speed: 20, scene: null, motion: 0,
  // what the safety controller and the advisor are told about the job
  playbackFacts() {
    if (!app.plan) return { cutter: "", handler: "", bar: "" };
    const b = app.plan.bar, dur = app.plan.summary.duration_s;
    const what = b.manual ? `manual cuts on a ${b.section} bar` : `${b.section} bar ${app.plan.bar_index + 1} of ${app.plan.bar_count}`;
    return { t: Math.round(app.t), bar: what,
      progress: (100 * app.t) / dur, cutter: stepAt(app.t, "Cutter"), handler: stepAt(app.t, "Handler") };
  },
};
window.app = app;                         // handy in the browser console
const $ = (id) => document.getElementById(id);

export function toast(msg, bad = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (bad ? " bad" : "");
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), bad ? 5000 : 2500);
}

export function fmtTime(s) {
  s = Math.max(0, Math.round(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- job
export function saveLocal() {
  try { localStorage.setItem("job", JSON.stringify(app.job)); } catch (e) { /* storage full or blocked */ }
}

export async function jobChanged() {
  saveLocal();
  renderPartList();
  try {
    app.bars = await post("/api/nest", { parts: app.job.parts, stock_length: app.job.stock_length });
  } catch (e) { app.bars = []; }
  app.barIndex = Math.min(app.barIndex, Math.max(app.bars.length - 1, 0));
  clearPlan();
  renderBars();
}

function renderBars() {
  const box = $("bars");
  box.innerHTML = "";
  const parts = app.job.parts;
  const totalKg = parts.reduce((s, p) => s + (p._weight || 0) * (p.qty || 1), 0);
  $("job-summary").textContent = `${parts.length} part type(s), ${parts.reduce((s, p) => s + (p.qty || 1), 0)} pieces` +
    (totalKg ? `, ${(totalKg / 1000).toFixed(2)} t` : "");
  if (!app.bars.length) { box.innerHTML = '<div class="muted">No bars yet - add parts on the Parts tab.</div>'; return; }
  app.bars.forEach((b, i) => {
    const div = document.createElement("div");
    div.className = "bar" + (i === app.barIndex ? " on" : "");
    const segs = b.placements.map((pl, k) => `<div class="seg" style="left:${(100 * pl.x0) / b.length}%;width:${(100 * (pl.x1 - pl.x0)) / b.length}%">${b.marks[k]}</div>`).join("") +
      b.scraps.map(([x0, x1]) => `<div class="seg scrap" style="left:${(100 * x0) / b.length}%;width:${Math.max((100 * (x1 - x0)) / b.length, 0.4)}%"></div>`).join("");
    div.innerHTML = `<b>Bar ${i + 1}</b> &nbsp;${b.section} &times; ${(b.length / 1000).toFixed(0)} m
      <span class="muted small">&nbsp;${(100 * b.used).toFixed(0)}% used</span><div class="strip">${segs}</div>`;
    div.onclick = () => { app.barIndex = i; clearPlan(); renderBars(); };
    box.appendChild(div);
  });
  const left = new Set();
  app.bars.forEach((b) => b.overflow.forEach((o) => left.add(`${app.job.parts[o.part]?.mark || "?"}: ${o.reason}`)));
}

// ---------------------------------------------------------------- planning
export function clearPlan() {
  if (app.playing) stopMachine("job changed");
  app.plan = null;
  app.t = 0;
  $("plan-info").innerHTML = "";
  $("plan-warnings").innerHTML = "";
  if (app.scene) { clearSteel(); manualPreview(); if (!manual.on) showBarPreview(); }
  updateTransport();
}

async function planBar() {
  if (manual.on) {
    $("loading").hidden = false;
    try { await planManual(); } catch (e) { toast("Planning failed: " + e.message, true); } finally { $("loading").hidden = true; }
    return;
  }
  if (!app.bars.length) return toast("Add some parts first (Parts & NC1 tab)", true);
  $("loading").hidden = false;
  try {
    const plan = await post("/api/plan", { parts: app.job.parts, stock_length: app.job.stock_length, bar: app.barIndex });
    loadPlan(plan);
  } catch (e) {
    toast("Planning failed: " + e.message, true);
  } finally {
    $("loading").hidden = true;
  }
}

export function loadPlan(plan) {
  if (app.playing) stopMachine("new plan loaded");
  app.plan = plan;
  app.t = 0;
  const s = plan.summary;
  $("plan-info").innerHTML = `<table>
    <tr><td>Cycle time</td><td><b>${fmtTime(s.duration_s)}</b></td></tr>
    <tr><td>${plan.manual ? "Pieces" : "Parts"}</td><td>${s.parts}</td></tr>
    <tr><td>Torch passes</td><td>${s.passes} (${s.cut_length_m.toFixed(1)} m of cutting)</td></tr>
    <tr><td>Torch on</td><td>${fmtTime(s.torch_on_s)} (${Math.round((100 * s.torch_on_s) / s.duration_s)}%)</td></tr>
    <tr><td>Bridges</td><td>never closer than ${s.min_bridge_gap_m.toFixed(2)} m</td></tr>
    <tr><td>Collision check</td><td class="${plan.collisions ? "bad" : "good"}">${plan.collisions ? plan.collisions + " problems" : "clear"}</td></tr>
    </table><div class="muted small">Planned in ${plan.planning_s} s</div>`;
  $("plan-warnings").innerHTML = plan.warnings.map((w) => `<div>&#9888; ${w}</div>`).join("");
  $("scrub").max = s.duration_s;
  buildSteel();
  manualPreview();                              // hides the manual stock bar: the plan draws the steel now
  updateTransport();
}

// ---------------------------------------------------------------- the steel in the 3D view
const steel = { parts: [], scraps: [], remnant: null, kerfs: [], preview: [] };

function clearSteel() {
  for (const p of steel.parts) { disposeGroup(p.group); disposeGroup(p.kerfGroup); }
  for (const s of steel.scraps) disposeGroup(s.mesh);
  for (const m of steel.preview) disposeGroup(m);
  if (steel.remnant) disposeGroup(steel.remnant);
  Object.assign(steel, { parts: [], scraps: [], remnant: null, kerfs: [], preview: [] });
}

async function showBarPreview() {
  // before planning: show the whole stock bar on the bed
  const b = app.bars[app.barIndex];
  if (!b) return;
  try {
    const sec = await get("/api/section?title=" + encodeURIComponent(b.section));
    if (app.plan) return;
    const mesh = stockMesh(sec, 0, b.length, MAT.steel, app.scene.origin);
    app.scene.steel.add(mesh);
    steel.preview.push(mesh);
  } catch (e) { /* section of a custom part: nothing to preview */ }
}

function buildSteel() {
  clearSteel();
  const plan = app.plan, origin = app.scene.origin;
  plan.placements.forEach((view, k) => {
    const kerfGroup = new THREE.Group();
    app.scene.steel.add(kerfGroup);
    // a manual piece too short to keep is drawn as a falling offcut (plan.drops), not as a part
    const hidden = !!plan.bar.placements[k].scrap;
    steel.parts.push({ view, k, key: "", group: new THREE.Group(), kerfGroup, hidden });
  });
  for (const c of plan.cuts) {
    const n = c.points.length;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    c.points.forEach((p, i) => pos.set(p, i * 3));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    geo.setDrawRange(0, 0);
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ vertexColors: true }));
    line.frustumCulled = false;
    steel.parts[c.placement].kerfGroup.add(line);
    steel.kerfs.push({ c, line, col });
  }
  const sec = plan.stock_section;
  for (const d of plan.drops) {
    const mesh = stockMesh(sec, d.x0, d.x1, d.remnant ? MAT.steel : MAT.scrap, origin);
    app.scene.steel.add(mesh);
    steel.scraps.push({ d, mesh, home: mesh.position.clone(), h: (sec.h || 200) / 1000 });
  }
  if (plan.bar.remnant && !plan.drops.some((d) => d.remnant)) {
    steel.remnant = stockMesh(sec, plan.bar.remnant[0], plan.bar.remnant[1], MAT.steel, origin);
    app.scene.steel.add(steel.remnant);
  }
  // carries: where the Handler's gantry was when each part came free
  for (const c of plan.carries) c.gFree = trackAt(plan.tracks.handler, c.t_free)[0];
  updateSteel(0);
}

function partState(k, t) {
  const plan = app.plan, ops = plan.ops.filter((o) => o.placement === k);
  const done = (o) => o.t_done <= t;
  const pl = plan.bar.placements[k];
  let start = ops.some((o) => o.kind === "start" && done(o));
  if (pl.start_shared) start = plan.ops.some((o) => o.placement === k - 1 && o.kind === "end" && done(o));
  const hasEnd = ops.some((o) => o.kind === "end");
  const end = hasEnd ? ops.some((o) => o.kind === "end" && done(o)) : true;
  const holes = new Set(ops.filter((o) => o.hole !== undefined && done(o)).map((o) => o.hole));
  const openings = new Set(ops.filter((o) => o.opening !== undefined && done(o)).map((o) => o.opening));
  return { start, end, holes, openings };
}

function partOffset(k, t) {
  for (const c of app.plan.carries) {
    if (c.placement !== k || t <= c.t_free) continue;
    if (t >= c.t_release) return c.offset;
    const g = trackAt(app.plan.tracks.handler, t)[0];
    return [g[0] - c.gFree[0], g[1] - c.gFree[1], g[2] - c.gFree[2]];
  }
  return [0, 0, 0];
}

function updateSteel(t) {
  const origin = app.scene.origin;
  for (const p of steel.parts) {
    if (p.hidden) continue;
    const st = partState(p.k, t);
    const free = app.plan.carries.some((c) => c.placement === p.k && t >= c.t_release);
    const key = `${st.start}|${st.end}|${[...st.holes]}|${[...st.openings]}|${free}`;
    if (key !== p.key) {
      disposeGroup(p.group);
      p.group = partGroup(p.view, st, free ? MAT.done : MAT.steel, origin);
      app.scene.steel.add(p.group);
      p.key = key;
    }
    const off = partOffset(p.k, t);
    p.group.position.set(...off);
    p.kerfGroup.position.set(...off);
  }
  // loose pieces fall straight down between the rollers (gravity) into the scrap tray;
  // a piece that is short and tall can't stand on its end, so it tips over flat
  const g = app.info.machine.g, drop = origin.z - app.scene.trayZ;
  for (const s of steel.scraps) {
    const dt = t - s.d.t, w = (s.d.x1 - s.d.x0) / 1000;
    let z = 0, tip = 0;
    if (dt > 0) z = Math.min(0.5 * g * dt * dt, drop);
    const landed = t - s.d.t_land;
    if (landed > 0 && w < 0.6 * s.h) tip = Math.min(landed / 0.35, 1) ** 2 * (Math.PI / 2);
    s.mesh.rotation.set(0, tip, 0);                     // turns about its bottom edge at the start end
    s.mesh.position.set(s.home.x, s.home.y, s.home.z - z + w * Math.sin(tip));
  }
  for (const k of steel.kerfs) {                      // kerf glows hot, then cools
    const times = k.c.times;
    let n = 0;
    while (n < times.length && times[n] <= t) n++;
    k.line.geometry.setDrawRange(0, n);
    if (n && t - times[n - 1] < 6) {
      for (let i = 0; i < n; i++) {
        const age = Math.min(Math.max(t - times[i], 0) / 5, 1);
        k.col.set([1.0 - 0.88 * age, 0.55 - 0.45 * age, 0.12 - 0.02 * age], i * 3);
      }
      k.line.geometry.attributes.color.needsUpdate = true;
    } else if (n && !k.cooled) {
      for (let i = 0; i < n; i++) k.col.set([0.12, 0.1, 0.1], i * 3);
      k.line.geometry.attributes.color.needsUpdate = true;
      k.cooled = n === times.length;
    }
  }
}

// ---------------------------------------------------------------- playback
function stepAt(t, who) {
  let text = who === "Handler" ? "waiting" : "ready";
  for (const [ts, w, m] of app.plan.steps) if (ts <= t + 1e-9 && w === who) text = m;
  return text;
}

function updateTransport() {
  const plan = app.plan, dur = plan ? plan.summary.duration_s : 0;
  $("btn-play").innerHTML = app.playing ? "&#10074;&#10074; Pause" : "&#9654; Run";
  $("time").textContent = `${fmtTime(app.t)} / ${fmtTime(dur)}`;
  $("scrub").value = app.t;
  const pill = $("pill-machine");
  const st = safety.status;
  if (st && ["ESTOP", "FAULT"].includes(st.state)) { pill.textContent = "STOPPED"; pill.className = "pill bad"; }
  else if (!plan) { pill.textContent = "Idle - plan a bar"; pill.className = "pill"; }
  else if (app.playing) { pill.textContent = "Running"; pill.className = "pill run"; }
  else if (app.t >= dur - 1e-6) { pill.textContent = "Bar finished"; pill.className = "pill ok"; }
  else { pill.textContent = app.t > 0 ? "Paused" : "Ready"; pill.className = "pill"; }
}

function updateHud() {
  const plan = app.plan;
  for (const [key, who] of [["cutter", "Cutter"], ["handler", "Handler"]]) {
    const el = $("hud-" + key);
    if (!plan) { el.innerHTML = '<div class="muted">parked</div>'; continue; }
    const [g, q] = trackAt(plan.tracks[key], app.t);
    el.innerHTML = `<div class="now">${stepAt(app.t, who)}</div><div class="axes">X ${g[0].toFixed(3)}  Y ${g[1].toFixed(3)}  Z ${g[2].toFixed(3)} m<br>` +
      `J ${q.map((a) => ((a * 180) / Math.PI).toFixed(0).padStart(4)).join(" ")}&deg;</div>`;
  }
}

let last = performance.now(), hudTimer = 0;
function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;
  const plan = app.plan, scene = app.scene;
  // motion only when the safety controller allows it, at the speed it allows;
  // category 0 (E-stop) stops at once, category 1/2 slow down over 0.6 s
  const st = safety.status;
  const allowed = plan && st && st.may_move && connected() && !safety.estopLocal;
  const target = allowed ? st.speed_factor : 0;
  if (target < app.motion) {
    const instant = !st || !connected() || safety.estopLocal || st.stop_category === 0 || st.state === "ESTOP";
    app.motion = instant ? target : Math.max(target, app.motion - dt / 0.6);
  } else app.motion = Math.min(target, app.motion + dt / 0.4);
  if (plan && app.motion > 0) {
    app.t = Math.min(app.t + dt * app.speed * app.motion, plan.summary.duration_s);
    if (app.t >= plan.summary.duration_s && st.state === "RUNNING") jobFinished();
  }
  if (plan) {
    for (const key of ["cutter", "handler"]) scene.pose(key, ...trackAt(plan.tracks[key], app.t));
    updateSteel(app.t);
    const on = plan.cuts.some((c) => c.t_on <= app.t && app.t <= c.times[c.times.length - 1]);
    scene.torch(on && app.motion > 0 && st && st.torch_allowed, dt, app.motion > 0);
  } else {
    for (const key of ["cutter", "handler"]) {
      const h = app.info.machine.hands[key];
      scene.pose(key, h.park, h.rest_q);
    }
    scene.torch(false, dt, false);
  }
  hudTimer += dt;
  if (hudTimer > 0.15) { hudTimer = 0; updateHud(); updateTransport(); }
  if (document.getElementById("tab-cell").classList.contains("on")) scene.render();
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------- start up
async function start() {
  app.info = await get("/api/info");
  app.sections = await get("/api/sections");
  const sel = $("stock-length");
  for (const m of app.info.codes.stock_lengths_m) sel.add(new Option(`${m} m`, m * 1000));
  // tabs
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab));
    window.dispatchEvent(new Event("resize"));
  }));
  app.scene = new CellScene($("cell-canvas"), app.info.machine);
  document.querySelectorAll(".views button").forEach((b) => (b.onclick = () => app.scene.view(b.dataset.view)));
  document.querySelectorAll(".speeds button").forEach((b) => (b.onclick = () => {
    app.speed = +b.dataset.speed;
    document.querySelectorAll(".speeds button").forEach((x) => x.classList.toggle("on", x === b));
  }));
  $("btn-plan").onclick = planBar;
  $("btn-play").onclick = async () => {
    if (app.playing) return stopMachine("pause button");
    if (!app.plan) await planBar();
    if (!app.plan) return;
    if (app.t >= app.plan.summary.duration_s - 1e-6) app.t = 0;
    const r = await startMachine();
    if (r && r.ok === false) toast("Can't start: " + r.why.join("; ") + " (see the Safety tab)", true);
  };
  $("btn-restart").onclick = () => { if (app.playing) stopMachine("back to start"); app.t = 0; updateTransport(); };
  $("scrub").oninput = (e) => {
    if (app.playing) { e.target.value = app.t; return toast("Stop the machine before jumping in time", true); }
    app.t = +e.target.value;
    updateTransport();
  };
  sel.onchange = () => { app.job.stock_length = +sel.value; jobChanged(); };
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.code === "Space" && document.getElementById("tab-cell").classList.contains("on")) { e.preventDefault(); $("btn-play").click(); }
  });

  // the job: last one used, or the examples
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem("job") || "null"); } catch (e) { saved = null; }
  if (saved && saved.parts && saved.parts.length) app.job = saved;
  else {
    app.job = { stock_length: 12000, parts: [] };
    for (const name of ["B1.nc1", "B2.nc1", "T1_tekla_style.nc1"]) {
      const v = await get("/api/examples/" + name);
      app.job.parts.push(Object.assign(v.part, { _weight: v.weight / v.part.qty }));
    }
  }
  sel.value = app.job.stock_length;
  initParts();
  initLibrary();
  initCamera();
  initHelp();
  initManual();
  await initSafety();
  await jobChanged();
  requestAnimationFrame(frame);
  memoryPill();
  setInterval(memoryPill, 15000);
}

async function memoryPill() {
  try {
    const s = await get("/api/system");
    const m = s.memory_mb;
    if (m) $("pill-memory").textContent = `RAM free ${m.available} MB`;
  } catch (e) { /* server busy */ }
}

start().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<div class="banner" style="position:fixed">Couldn't start: ${e.message}</div>`); console.error(e); });
