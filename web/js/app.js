// Beam Cell - the app: job state, tabs, planning and playback of the machine.
import * as THREE from "three";
import { get, post } from "./api.js";
import { CellScene } from "./scene.js";
import { trackAt } from "./kinematics.js";
import { MAT, partGroup, stockMesh, disposeGroup } from "./geometry.js";
import { initParts, renderPartList, clearAllParts, partsRemoved } from "./parts.js";
import { initLibrary } from "./library.js";
import { initPrototype } from "./prototype.js";
import { initCamera } from "./camera.js";
import { initHelp } from "./help.js";
import { initSafety, safety, connected, startMachine, stopMachine, jobFinished, loadJob, clearSafetyJob } from "./safety.js";
import { initJobs, openJobs } from "./jobs.js";
import { initSensors, barCheckHtml } from "./sensors.js";
import { initManual, manual, manualPreview, planManual, render as renderManual } from "./manual.js";
import { initPlasma, refreshPlasmaPick } from "./plasma.js";
import { initReports } from "./reports.js";

export const app = {
  info: null, sections: null, job: { stock_length: 12000, parts: [] }, bars: [], barIndex: 0,
  plan: null, t: 0, playing: false, speed: 20, scene: null, motion: 0,
  // what the safety controller and the advisor are told about the job
  playbackFacts() {
    if (!app.plan) return { cutter: "", handler: "", bar: "" };
    const b = app.plan.bar, dur = app.plan.summary.duration_s;
    const what = b.manual ? `manual cuts on a ${b.section} bar` : `${b.section} bar ${app.plan.bar_index + 1} of ${app.plan.bar_count}`;
    return { t: Math.round(app.t), bar: what,
      progress: (100 * app.t) / dur, cutter: stepAt(app.t, "Cutter"), handler: stepAt(app.t, "Handler"),
      plasma: (app.plan.process && app.plan.process.preset) || "" };
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
    div.innerHTML = `<button class="mini danger del-bar" title="Take this bar's parts out of the job">&#128465;</button>
      <b>Bar ${i + 1}</b> &nbsp;${b.section} &times; ${(b.length / 1000).toFixed(0)} m
      <span class="muted small">&nbsp;${(100 * b.used).toFixed(0)}% used</span><div class="strip">${segs}</div>`;
    div.onclick = () => { app.barIndex = i; clearPlan(); renderBars(); };
    div.querySelector(".del-bar").onclick = async (e) => {
      e.stopPropagation();
      if (safety.status && safety.status.state === "RUNNING") return toast("Stop the machine before changing the job", true);
      const what = barContents(b).join(", ");
      if (!confirm(`Delete bar ${i + 1} (${b.section})? Its parts come out of the job: ${what}.`)) return;
      await removeBarParts(b);
      toast(`Bar ${i + 1} deleted: ${what}`);
    };
    box.appendChild(div);
  });
  const left = new Set();
  app.bars.forEach((b) => b.overflow.forEach((o) => left.add(`${app.job.parts[o.part]?.mark || "?"}: ${o.reason}`)));
}

// The part marks on a bar, one per piece: a nested bar lists them in .marks, a plan in .placements.
function barMarks(bar) {
  return bar.marks || bar.placements.map((pl) => pl.part.mark);
}

// What a bar holds, e.g. ["B1 x2", "T1 x1"].
function barContents(bar) {
  const n = {};
  for (const m of barMarks(bar)) n[m] = (n[m] || 0) + 1;
  return Object.entries(n).map(([m, c]) => `${m} x${c}`);
}

// Take the parts on a bar out of the job (they've been cut, or the bar was deleted); the rest re-nest.
async function removeBarParts(bar) {
  const n = {};
  for (const m of barMarks(bar)) n[m] = (n[m] || 0) + 1;
  for (const p of app.job.parts) {
    const take = Math.min(n[p.mark] || 0, p.qty || 1);
    p.qty = (p.qty || 1) - take;
    n[p.mark] = (n[p.mark] || 0) - take;
  }
  app.job.parts = app.job.parts.filter((p) => p.qty > 0);
  app.barIndex = 0;
  partsRemoved();
  await jobChanged();
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
  refreshPlasmaPick();                          // the beam may have changed: its saved plasma settings
}

async function planBar() {
  if (manual.on) {
    $("loading").hidden = false;
    try { await planManual(); } catch (e) { toast("Planning failed: " + e.message, true); } finally { $("loading").hidden = true; }
    return;
  }
  if (!app.bars.length) return toast("Add some parts first (Parts tab)", true);
  $("loading").hidden = false;
  try {
    const plan = await post("/api/plan", { parts: app.job.parts, stock_length: app.job.stock_length, bar: app.barIndex,
                                         plasma: app.plasma || "" });
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
  plan.jobName = jobName(plan);
  loadJob(plan.jobName, plan.plan_id).then(showJobNow);
  const s = plan.summary;
  $("plan-info").innerHTML = `<table>
    <tr><td>Cycle time</td><td><b>${fmtTime(s.duration_s)}</b></td></tr>
    <tr><td>${plan.manual ? "Pieces" : "Parts"}</td><td>${s.parts}</td></tr>
    <tr><td>Torch passes</td><td>${s.passes} (${s.cut_length_m.toFixed(1)} m of cutting)</td></tr>
    <tr><td>Torch on</td><td>${fmtTime(s.torch_on_s)} (${Math.round((100 * s.torch_on_s) / s.duration_s)}%)</td></tr>
    <tr><td>Bridges</td><td>never closer than ${s.min_bridge_gap_m.toFixed(2)} m</td></tr>
    <tr><td>Collision check</td><td class="${plan.collisions ? "bad" : "good"}">${plan.collisions ? plan.collisions + " problems" : "clear"}</td></tr>
    <tr><td>Plasma</td><td>${plan.process ? plan.process.label : "-"}<br><span class="small ${plan.process && plan.process.preset ? "good" : "muted"}">${
      plan.process && plan.process.preset ? "saved settings: " + plan.process.preset : "cut chart values"}</span></td></tr>
    </table><div class="muted small">Planned in ${plan.planning_s} s</div>
    ${plan.bar_check ? `<details class="bar-check"><summary class="${plan.bar_check.ok ? "good" : "bad"}">Bar check: ${plan.bar_check.ok
      ? "the bar on the bed matches the job" : `the bar doesn't match the job (${plan.bar_check.problems.length})`}
      ${plan.bar_check.simulated ? "(simulated)" : ""}</summary><div class="muted small">Measured again when you press Start - the job only
      starts if the bar matches.</div>${barCheckHtml(plan.bar_check)}</details>` : ""}`;
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

// ---------------------------------------------------------------- jobs and safety
// A job = one planned bar (or a set of manual cuts). The safety controller knows which job is
// loaded; each one needs its own pre-start checklist, and a finished job asks what to do next.
function jobName(plan) {
  const name = ($("job-name") && $("job-name").value.trim()) || "Job";
  return plan.manual ? `Manual cuts - ${plan.bar.section} x ${plan.bar.length} mm`
    : `${name} - bar ${plan.bar_index + 1} of ${plan.bar_count} (${plan.bar.section})`;
}

function showJobNow() {
  const st = safety.status, el = $("job-now");
  if (!el) return;
  const job = st && st.job;
  el.innerHTML = job ? `Loaded: <b>${job.name}</b> &middot; ${job.state === "finished" ? "finished" : job.state}
    &middot; checklist ${st.checklist_ok ? '<span class="good">done</span>' : '<span class="warn">needed</span>'}
    <button id="btn-job-clear" class="danger mini" title="Delete this job">Clear job</button>` : "No job loaded - plan a bar.";
  if ($("btn-job-clear")) $("btn-job-clear").onclick = () => clearJob();
}
setInterval(showJobNow, 1000);

// what the job history keeps about the loaded job
function jobDetails(plan = app.plan) {
  if (!plan) return {};
  return { section: plan.bar.section, parts: plan.summary.parts, duration_s: plan.summary.duration_s,
    what: plan.manual ? `manual cuts on a ${plan.bar.length} mm bar` : `bar ${plan.bar_index + 1} of ${plan.bar_count}, ${plan.bar.length} mm` };
}

let finishing = false;
async function finishJob() {
  if (finishing) return;
  finishing = true;
  await jobFinished(jobDetails());                 // goes into the job history
  const plan = app.plan, dlg = $("job-done");
  // the bar is done: its parts come off the Machine tab (they're in the job history); the rest re-nest
  let cut = [], before = null;
  if (!plan.manual) {
    before = app.job.parts.map((p) => Object.assign({}, p));
    cut = barContents(plan);
    await removeBarParts(plan);
    await clearSafetyJob();
    showJobNow();
  }
  $("job-done-what").innerHTML = `<p><b>${plan.jobName}</b><br>${plan.summary.parts} ${plan.manual ? "piece(s)" : "part(s)"} cut in ${fmtTime(plan.summary.duration_s)}.</p>` +
    (plan.manual ? "" : `<p class="small">Cut and taken off the job: <b>${cut.join(", ")}</b> - they're in the job history.
      ${app.bars.length ? `${app.bars.length} bar(s) still to cut.` : "Nothing left to cut."}</p>`);
  const more = !plan.manual && app.bars.length > 0;
  $("jd-next").hidden = !more;
  $("jd-next").textContent = `Plan the next bar (${app.bars.length} left)`;
  $("jd-next").onclick = async () => { dlg.close(); app.barIndex = 0; clearPlan(); renderBars(); await planBar(); toast("Next bar planned - confirm the checklist (Safety tab), then Run"); };
  $("jd-clear").textContent = plan.manual ? "Delete these cuts" : "Delete the rest of the job";
  $("jd-clear").hidden = !plan.manual && !app.bars.length;
  $("jd-again").textContent = plan.manual ? "Run these cuts again" : "Cut the same bar again";
  $("jd-again").onclick = async () => {
    dlg.close();
    if (before) { app.job.parts = before; await jobChanged(); app.barIndex = plan.bar_index; renderBars(); await planBar(); }
    else { app.t = 0; loadJob(plan.jobName); updateTransport(); }
    toast("Ready to run again - confirm the checklist first (Safety tab)");
  };
  $("jd-clear").onclick = async () => { dlg.close(); await clearJob(true); };
  $("jd-history").onclick = () => { dlg.close(); openJobs(); };
  $("jd-keep").onclick = () => dlg.close();
  dlg.onclose = () => { finishing = false; };
  if (!dlg.open) dlg.showModal();
}

// Delete the current job: its parts (or manual cuts), its plan, and the job in the safety controller.
export async function clearJob(confirmed = false) {
  if (safety.status && safety.status.state === "RUNNING") return toast("Stop the machine before clearing the job", true);
  const what = manual.on ? "all the manual cuts" : "every part in this job";
  if (!confirmed && !confirm(`Clear the job? This removes ${what} and its plan.`)) return;
  await clearSafetyJob(jobDetails());
  if (manual.on) { manual.job.cuts = []; try { localStorage.setItem("manual", JSON.stringify(manual.job)); } catch (e) { /* blocked */ } renderManual(); }
  else await clearAllParts();
  clearPlan();
  showJobNow();
  toast("Job cleared");
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
    // the Cutter shows the plasma settings of the cut it is doing
    const c = key === "cutter" && plan.cuts.find((c) => c.t_on <= app.t && app.t <= c.times[c.times.length - 1]);
    const p = c && c.process;
    const torch = p ? `<div class="axes torch">${p.amps ? p.amps + " A &middot; " : ""}${p.speed_mm_min} mm/min &middot; height ${p.cut_height_mm} mm` +
      `${p.arc_voltage_v ? " &middot; " + p.arc_voltage_v + " V" : ""} &middot; THC ${p.thc.split(" ")[0]} &middot; ${p.thickness_mm} mm ${p.feature}</div>` : "";
    el.innerHTML = `<div class="now">${stepAt(app.t, who)}</div>${torch}<div class="axes">X ${g[0].toFixed(3)}  Y ${g[1].toFixed(3)}  Z ${g[2].toFixed(3)} m<br>` +
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
  // Manual mode: letting go of "Hold to move" stops at once, here - not when the server next answers
  const released = st && st.mode === "MANUAL" && !safety.holding;
  const allowed = plan && st && st.may_move && connected() && !safety.estopLocal && !released;
  const target = allowed ? st.speed_factor : 0;
  if (target < app.motion) {
    const instant = !st || !connected() || safety.estopLocal || released || st.stop_category === 0 || st.state === "ESTOP";
    app.motion = instant ? target : Math.max(target, app.motion - dt / 0.6);
  } else app.motion = Math.min(target, app.motion + dt / 0.4);
  if (plan && app.motion > 0) {
    app.t = Math.min(app.t + dt * app.speed * app.motion, plan.summary.duration_s);
  }
  // the loaded job has reached its end (running, or paused right at the end): finish it once
  if (plan && app.t >= plan.summary.duration_s && st && st.job && st.job.state !== "finished" && st.job.started
      && st.job.name === plan.jobName) finishJob();
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
  $("version").textContent = "v " + (app.info.version || "").split(" ")[0];       // the git commit: shows a git pull + restart worked
  $("version").title = "Software version " + app.info.version;
  const sel = $("stock-length");
  for (const m of app.info.codes.stock_lengths_m) sel.add(new Option(`${m} m`, m * 1000));
  // tabs
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab));
    window.dispatchEvent(new Event("resize"));
  }));
  app.scene = new CellScene($("cell-canvas"), app.info.machine);
  try { await app.scene.load(); }
  catch (e) { console.warn(e); toast("The machine's 3D model files are missing (web/models) - run: python3 -m beamcell.cad cell", true); }
  hoverLabels();
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
    if (r && r.ok === false && !(r.job && r.job.bar_check && !r.job.bar_check.ok))   // a bar that doesn't match has its own window
      toast("Can't start: " + r.why.join("; ") + " (see the Safety tab)", true);
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
  initJobs();
  initLibrary();
  initPrototype();
  initCamera();
  initSensors();
  initHelp();
  initManual();
  await initPlasma();
  initReports();
  await initSafety();
  await jobChanged();
  requestAnimationFrame(frame);
  memoryPill();
  setInterval(memoryPill, 15000);
}

// point at anything in the 3D view to see what it is (the CAD model's labels)
function hoverLabels() {
  const canvas = $("cell-canvas"), tip = $("hover-label");
  let pending = null, buttons = 0;
  canvas.addEventListener("pointerdown", (e) => { buttons = e.buttons; tip.hidden = true; });
  canvas.addEventListener("pointerup", () => { buttons = 0; });
  canvas.addEventListener("pointerleave", () => { tip.hidden = true; });
  canvas.addEventListener("pointermove", (e) => {
    if (buttons || pending) return;
    pending = setTimeout(() => {
      pending = null;
      const r = canvas.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      const label = app.scene.labelAt(ndc);
      tip.hidden = !label;
      if (label) {
        tip.textContent = label;
        tip.style.left = `${e.clientX - r.left + 14}px`;
        tip.style.top = `${e.clientY - r.top + 12}px`;
      }
    }, 120);
  });
}

async function memoryPill() {
  try {
    const s = await get("/api/system");
    const m = s.memory_mb;
    if (m) $("pill-memory").textContent = `RAM free ${m.available} MB`;
  } catch (e) { /* server busy */ }
}

start().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<div class="banner" style="position:fixed">Couldn't start: ${e.message}</div>`); console.error(e); });
