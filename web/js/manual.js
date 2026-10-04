// Manual cutting: put holes, cuts and notches on a bar by hand (or by clicking the steel in 3D),
// check them against the UK rules, then plan and run them like any job - same safety rules.
import * as THREE from "three";
import { get, post } from "./api.js";
import { app, toast, loadPlan, clearPlan } from "./app.js";
import { stockMesh, MAT, holeOutline, faceToSection } from "./geometry.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const r1 = (v) => Math.round(v * 10) / 10;

export const manual = {
  on: false,
  job: { section: "UB 305x165x40", length: 6000, cuts: [] },
  sec: null,               // the section's sizes (from the server)
  check: null,             // last /api/manual/check answer
  click: "hole",           // what a click on the steel adds: hole | cut | off
  snap: true,              // snap holes to the centre line of the face
  group: null,             // 3D markers
};

function save() { try { localStorage.setItem("manual", JSON.stringify(manual.job)); } catch (e) { /* blocked */ } }

// ---------------------------------------------------------------- the panel
export function initManual() {
  try { Object.assign(manual.job, JSON.parse(localStorage.getItem("manual") || "{}")); } catch (e) { /* ignore */ }
  manual.group = new THREE.Group();
  app.scene.scene.add(manual.group);
  $("mode-job").onclick = () => setMode(false);
  $("mode-manual").onclick = () => setMode(true);
  const canvas = $("cell-canvas");
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", (e) => {
    if (!manual.on || manual.click === "off" || !down || e.button !== 0) return;
    if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;   // that was a drag (turning the view)
    clickSteel(e);
  });
}

function setMode(on) {
  manual.on = on;
  $("mode-job").classList.toggle("on", !on);
  $("mode-manual").classList.toggle("on", on);
  $("job-panel").hidden = on;
  $("manual-panel").hidden = !on;
  $("btn-plan").textContent = on ? "Plan these cuts" : "Plan this bar";
  manual.group.visible = on;
  if (on) render();
  clearPlan();
}

async function loadSection() {
  manual.sec = await get("/api/section?title=" + encodeURIComponent(manual.job.section));
}

function sectionPicker() {
  const fams = Object.keys(app.sections).filter((f) => app.sections[f].some((s) => s.cuttable));
  const fam = manual.job.section.split(" ")[0];
  return `<select id="mc-fam">${fams.map((f) => `<option ${f === fam ? "selected" : ""}>${f}</option>`).join("")}</select>
    <select id="mc-sec">${(app.sections[fam] || []).map((s) => `<option ${s.title === manual.job.section ? "selected" : ""}>${s.title}</option>`).join("")}</select>`;
}

function faceOptions(face) {
  const k = manual.sec?.kind;
  const opts = k === "L" ? [["v", "upright leg"], ["u", "flat leg"]] : [["v", "web"], ["o", "top flange"]];
  return opts.map(([v, t]) => `<option value="${v}" ${v === face ? "selected" : ""}>${t}</option>`).join("");
}

function boltFor(d) {
  for (const b of app.info.codes.bolts) if (Math.abs(app.info.codes.hole_sizes[b].normal[0] - d) < 0.01) return b;
  return "";
}

export async function render() {
  if (!manual.sec || manual.sec.title !== manual.job.section) await loadSection();
  const j = manual.job;
  const cutXs = [0, ...j.cuts.filter((c) => c.type === "cut").map((c) => c.x)];
  const rows = j.cuts.map((c, i) => {
    let body;
    if (c.type === "hole") {
      const bolt = boltFor(c.d);
      body = `<select data-f="face">${faceOptions(c.face)}</select>
        x <input type="number" data-f="x" value="${c.x}"> y <input type="number" data-f="y" value="${c.y ?? ""}" placeholder="mid">
        <select data-f="bolt">${app.info.codes.bolts.map((b) => `<option ${b === bolt ? "selected" : ""}>${b}</option>`).join("")}<option value="" ${bolt ? "" : "selected"}>other</option></select>
        &Oslash; <input type="number" data-f="d" value="${c.d}" step="0.5">`;
    } else if (c.type === "cut") {
      body = `at x <input type="number" data-f="x" value="${c.x}"> angle <input type="number" data-f="angle" value="${c.angle || 0}"> &deg;`;
    } else {
      body = `at <select data-f="x">${cutXs.map((x) => `<option value="${x}" ${Math.abs(x - c.x) < 1 ? "selected" : ""}>${x ? "cut x " + x : "bar start"}</option>`).join("")}</select>
        <select data-f="on"><option value="after" ${c.on !== "before" ? "selected" : ""}>piece after</option><option value="before" ${c.on === "before" ? "selected" : ""}>piece before</option></select>
        <select data-f="side"><option ${c.side !== "bottom" ? "selected" : ""}>top</option><option ${c.side === "bottom" ? "selected" : ""}>bottom</option></select>
        N <input type="number" data-f="length" value="${c.length}"> n <input type="number" data-f="depth" value="${c.depth}">`;
    }
    return `<div class="mc-row" data-i="${i}"><b>${i + 1}</b> <span class="mc-type ${c.type}">${c.type}</span> ${body}
      <button class="mini" data-del="${i}" title="remove">&times;</button></div>`;
  }).join("");
  $("manual-panel").innerHTML = `
    <p class="muted small">Cut what you want, now: add holes, cuts and notches (or click on the steel), check them, then plan and Run.
      The same UK checks and safety rules apply. x is measured from the bar's start (the infeed end).</p>
    <label class="row">Section ${sectionPicker()}</label>
    <label class="row">Bar length mm <input id="mc-len" type="number" value="${j.length}" min="300" max="12000" step="10"></label>
    <div class="toolbar">
      <button id="mc-add-hole">+ Hole</button><button id="mc-add-cut">+ Cut</button><button id="mc-add-notch">+ Notch</button>
      <button id="mc-clear" class="ghost">Clear</button>
    </div>
    <div class="toolbar small">Click on the steel adds:
      <label><input type="radio" name="mc-click" value="hole" ${manual.click === "hole" ? "checked" : ""}> hole</label>
      <label><input type="radio" name="mc-click" value="cut" ${manual.click === "cut" ? "checked" : ""}> cut</label>
      <label><input type="radio" name="mc-click" value="off" ${manual.click === "off" ? "checked" : ""}> nothing</label>
      <label title="Put clicked holes on the centre line of the web / flange"><input type="checkbox" id="mc-snap" ${manual.snap ? "checked" : ""}> centre line</label>
    </div>
    <div class="mc-list">${rows || '<div class="muted">No cuts yet.</div>'}</div>
    <div id="mc-check" class="checks"></div>`;
  wire();
  markers();
  checkSoon();
}

function wire() {
  const j = manual.job;
  const changed = (rerender = false) => { save(); clearPlan(); if (rerender) render(); else { markers(); checkSoon(); } };
  $("mc-fam").onchange = (e) => { j.section = app.sections[e.target.value].find((s) => s.cuttable).title; changed(true); };
  $("mc-sec").onchange = (e) => { j.section = e.target.value; changed(true); };
  $("mc-len").onchange = (e) => { j.length = Math.max(300, Math.min(12000, +e.target.value)); changed(true); };
  $("mc-add-hole").onclick = () => { j.cuts.push(newHole("v", freeX(0.25))); changed(true); };
  $("mc-add-cut").onclick = () => { j.cuts.push({ type: "cut", x: freeX(0.5), angle: 0 }); changed(true); };
  $("mc-add-notch").onclick = () => {
    const sup = manual.sec, depth = Math.ceil((sup.tf || 10) + (sup.r || 10) + 2);
    j.cuts.push({ type: "notch", x: 0, on: "after", side: "top", length: 100, depth, radius: 10 });
    changed(true);
  };
  $("mc-clear").onclick = () => { j.cuts = []; changed(true); };
  document.querySelectorAll("input[name=mc-click]").forEach((el) => (el.onchange = () => { manual.click = el.value; }));
  $("mc-snap").onchange = (e) => { manual.snap = e.target.checked; };
  document.querySelectorAll(".mc-row").forEach((row) => {
    const c = j.cuts[+row.dataset.i];
    row.querySelectorAll("[data-f]").forEach((el) => (el.onchange = () => {
      const f = el.dataset.f;
      if (f === "bolt") { if (el.value) c.d = app.info.codes.hole_sizes[el.value].normal[0]; return changed(true); }
      if (f === "y") { if (el.value === "") delete c.y; else c.y = +el.value; return changed(); }
      c[f] = ["face", "on", "side"].includes(f) ? el.value : +el.value;
      changed(f === "face" || (c.type === "cut" && f === "x"));
    }));
  });
  document.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => { j.cuts.splice(+b.dataset.del, 1); changed(true); }));
}

// A place along the bar for a new hole or cut: near `frac` of the length, at least 150 mm from
// any cut, hole or end already there (so a new item doesn't start with a rule broken).
function freeX(frac) {
  const j = manual.job, taken = [0, j.length, ...j.cuts.map((c) => c.x)];
  for (let k = 0; k < 40; k++) {
    const x = Math.round((j.length * frac + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 100) / 10) * 10;
    if (x > 150 && x < j.length - 150 && taken.every((t) => Math.abs(t - x) >= 150)) return x;
  }
  return Math.round(j.length * frac);
}

function newHole(face, x, y) {
  const d = app.info.codes.hole_sizes[app.info.codes.standard_bolt].normal[0];
  const h = { type: "hole", face, x, d };
  if (y !== undefined) h.y = y;
  return h;
}

// ---------------------------------------------------------------- checks
let timer = null;
function checkSoon() {
  clearTimeout(timer);
  timer = setTimeout(runCheck, 250);
}

async function runCheck() {
  const box = $("mc-check");
  if (!box) return;
  try {
    manual.check = await post("/api/manual/check", manual.job);
  } catch (e) { box.textContent = "check failed: " + e.message; return; }
  const ck = manual.check;
  const pieces = ck.pieces.map((p) => `<li><b>${p.mark}</b> ${Math.round(p.x0)}&ndash;${Math.round(p.x1)} mm (${Math.round(p.length)} mm, ${p.weight} kg)
    &rarr; ${p.keep ? "stays on the rollers" : p.scrap ? "falls into the scrap tray" : "Handler puts it on the outfeed table"}</li>`).join("");
  const probs = ck.problems.map((p) => `<div class="${p.level === "error" ? "bad" : "warn"}">${p.level === "error" ? "&#10006;" : "&#9888;"} ${esc(p.item)}: ${esc(p.text)}
    ${p.ref ? `<span class="muted small">(${esc(p.ref)})</span>` : ""}</div>`).join("");
  box.innerHTML = `${probs || (manual.job.cuts.length ? '<div class="good">&#10004; All cuts pass the UK checks</div>' : "")}
    ${pieces ? `<div class="small">The bar becomes:<ul>${pieces}</ul></div>` : ""}`;
}

export async function planManual() {
  if (!manual.job.cuts.length) return toast("Add a hole, cut or notch first", true);
  const plan = await post("/api/manual/plan", manual.job);
  if (plan.error) return toast(plan.error, true);
  loadPlan(plan);
}

// ---------------------------------------------------------------- 3D: the bar, markers and clicking on it
// The stock bar in manual mode. Kept (not rebuilt) while the section and length stay the same,
// so a click on it always lands - even when the click also finishes editing a number box.
export async function manualPreview() {
  if (manual.on && (!manual.sec || manual.sec.title !== manual.job.section)) await loadSection();
  const key = `${manual.job.section}|${manual.job.length}`;
  if (manual.on && manual.sec && manual.barKey !== key) {
    if (manual.bar) { app.scene.steel.remove(manual.bar); manual.bar.geometry.dispose(); }
    manual.bar = stockMesh(manual.sec, 0, manual.job.length, MAT.steel, app.scene.origin);
    manual.bar.userData.manualBar = true;
    app.scene.steel.add(manual.bar);
    manual.barKey = key;
  }
  if (manual.bar) manual.bar.visible = manual.on && !app.plan;
  markers();
}

function markers() {
  const g = manual.group;
  if (!g) return;
  for (const c of [...g.children]) { g.remove(c); c.geometry?.dispose(); }
  const sec = manual.sec, o = app.scene.origin;
  if (!sec || !manual.on) return;
  const red = new THREE.LineBasicMaterial({ color: 0xff2a1f, depthTest: false, transparent: true });
  const line = (pts) => { const l = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), red); l.renderOrder = 5; g.add(l); };
  for (const c of manual.job.cuts) {
    if (c.type === "hole") {
      const y = c.y ?? centre(sec, c.face);
      const ring = holeOutline({ x: c.x, y, d: c.d });
      if (c.face === "v" || c.face === "h") {
        const u = sec.kind === "I" ? sec.tw / 2 : sec.b / 2;
        line(ring.map(([x, yy]) => new THREE.Vector3(o.x + x / 1000, o.y + (u + 2) / 1000, o.z + yy / 1000)));
        if (sec.kind === "I") line(ring.map(([x, yy]) => new THREE.Vector3(o.x + x / 1000, o.y - (u + 2) / 1000, o.z + yy / 1000)));
      } else {
        const z = c.face === "o" ? sec.h : sec.t || sec.tf;
        line(ring.map(([x, yy]) => new THREE.Vector3(o.x + x / 1000, o.y + faceToSection(sec, c.face, yy) / 1000, o.z + (z + 2) / 1000)));
      }
    } else if (c.type === "cut") {
      const t = Math.tan(((c.angle || 0) * Math.PI) / 180);
      const outline = sec.outline;   // section outline (u, v) mm: draw it where the cut line is at each height
      line(outline.map(([u, v]) => new THREE.Vector3(o.x + (c.x + t * (sec.h / 2 - v)) / 1000, o.y + u / 1000, o.z + v / 1000)));
    } else {
      const x0 = c.on === "before" ? c.x - c.length : c.x, x1 = x0 + c.length;
      const v0 = c.side === "top" ? sec.h - c.depth : 0, v1 = c.side === "top" ? sec.h : c.depth;
      for (const u of [-sec.b / 2 - 2, sec.b / 2 + 2])
        line([[x0, v0], [x1, v0], [x1, v1], [x0, v1]].map(([x, v]) => new THREE.Vector3(o.x + x / 1000, o.y + u / 1000, o.z + v / 1000)));
    }
  }
}

function centre(sec, face) {
  if (sec.kind === "L") return Math.min(50, (face === "v" ? sec.h : sec.b) / 2);
  return face === "v" || face === "h" ? sec.h / 2 : sec.b / 2;
}

function clickSteel(e) {
  const sc = app.scene, rect = e.target.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(ndc, sc.camera);
  const hit = ray.intersectObjects(sc.steel.children, true).find((h) => h.object.isMesh && h.face && h.object.visible);
  if (!hit) return toast("Click on the steel bar to place a " + manual.click, true);
  const sec = manual.sec, o = sc.origin, p = hit.point;
  const n = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
  const x = Math.round((p.x - o.x) * 1000 / 5) * 5;            // 5 mm steps
  const u = (p.y - o.y) * 1000, v = (p.z - o.z) * 1000;
  if (x < 0 || x > manual.job.length) return;
  if (manual.click === "cut") {
    manual.job.cuts.push({ type: "cut", x, angle: 0 });
  } else {
    let face = null, y = null;
    if (n.z > 0.7 && v > sec.h - (sec.tf || sec.t) - 1) { face = sec.kind === "L" ? null : "o"; y = sec.b / 2 - u; }
    else if (n.z > 0.7 && sec.kind === "L") { face = "u"; y = sec.b / 2 - u; }
    else if (Math.abs(n.y) > 0.7) { face = "v"; y = v; }
    if (!face) return toast("Click the web (from either side) or the top flange to place a hole", true);
    if (manual.snap) y = centre(sec, face);
    manual.job.cuts.push(newHole(face, x, manual.snap ? undefined : r1(y)));
  }
  save();
  clearPlan();
  render();
  toast(`Added a ${manual.click} at x = ${x} mm`);
}
