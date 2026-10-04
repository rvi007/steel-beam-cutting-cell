// Parts tab: the part list, NC1 import, the part editor (UK bolts, notches, mitres) and a
// 2D drawing of every face with the code checks.
import { get, post, download } from "./api.js";
import { app, jobChanged, toast, saveLocal } from "./app.js";
import { holeOutline } from "./geometry.js";

const $ = (id) => document.getElementById(id);
const CUT_FAMILIES = ["UB", "UC", "UBP", "PFC", "EA", "UA"];
let selected = 0;
let checkTimer = null;
let lastView = null;

const FACE_NAMES = {
  I: { o: "Top flange", v: "Web", u: "Bottom flange" },
  U: { o: "Top flange", v: "Web (back)", u: "Bottom flange" },
  L: { v: "Upright leg", u: "Flat leg" },
};

function sectionOf(title) {
  for (const rows of Object.values(app.sections)) for (const s of rows) if (s.title === title) return s;
  return null;
}

// ---------------------------------------------------------------- list
export function renderPartList() {
  const tbody = document.querySelector("#part-list tbody");
  tbody.innerHTML = "";
  app.job.parts.forEach((p, i) => {
    const tr = document.createElement("tr");
    if (i === selected) tr.className = "sel";
    const status = p._errors ? `<span class="bad" title="has errors">&#10007;</span>` : `<span class="good">&#10003;</span>`;
    tr.innerHTML = `<td><b>${esc(p.mark)}</b></td><td>${esc(p.section)}</td><td>${p.length.toFixed(0)}</td><td>${p.qty}</td>` +
      `<td>${p._weight ? (p._weight * p.qty).toFixed(0) : ""}</td><td>${status}</td>`;
    tr.onclick = () => { selected = i; renderPartList(); renderEditor(); };
    tbody.appendChild(tr);
  });
  if (!app.job.parts.length) tbody.innerHTML = '<tr><td colspan="6" class="muted">No parts yet - import NC1 files or add a part.</td></tr>';
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---------------------------------------------------------------- import
async function importFiles(files) {
  const lines = [];
  for (const f of files) {
    try {
      const v = await post("/api/nc1", { filename: f.name, text: await f.text() });
      addPart(v);
      const errs = v.checks.filter((c) => c.level === "error").length;
      lines.push(`<div><b>${esc(f.name)}</b>: ${v.report.map(esc).join(" &middot; ")}${errs ? ` <span class="bad">&middot; ${errs} problem(s)</span>` : ""}</div>`);
    } catch (e) {
      lines.push(`<div class="bad"><b>${esc(f.name)}</b>: ${esc(e.message)}</div>`);
    }
  }
  $("import-report").innerHTML = "<h3>Import report</h3>" + lines.join("");
  await jobChanged();
  renderEditor();
}

function addPart(view) {
  const part = Object.assign(view.part, { _weight: view.weight / view.part.qty, _errors: view.checks.some((c) => c.level === "error") });
  app.job.parts.push(part);
  selected = app.job.parts.length - 1;
}

function newPart() {
  const n = app.job.parts.length + 1;
  const base = app.job.parts[selected];
  return { mark: `P${n}`, section: base ? base.section : "UB 305x165x40", length: 3000, qty: 1, grade: app.info.codes.default_grade,
    holes: [], outlines: {}, inner: [], copes: [], mitres: {}, source: "manual", custom: null };
}

// ---------------------------------------------------------------- editor
function field(label, html) { return `<label class="f">${label}${html}</label>`; }
function num(id, v, step = 1) { return `<input type="number" data-k="${id}" value="${+(+v).toFixed(2)}" step="${step}">`; }

export function renderEditor() {
  const ed = $("editor");
  const p = app.job.parts[selected];
  if (!p) { ed.innerHTML = '<p class="muted">Select a part on the left, import NC1 files, or press <b>+ New part</b>.</p>'; return; }
  const sec = sectionOf(p.section) || p.custom || {};
  const kind = sec.kind || "I";
  const fromFile = p.outlines && Object.keys(p.outlines).length > 0;
  const fam = (sec.family || "UB");
  const famOpts = CUT_FAMILIES.map((f) => `<option ${f === fam ? "selected" : ""} value="${f}">${f} - ${app.info.families[f]}</option>`).join("");
  const sizeOpts = (app.sections[fam] || []).map((s) => `<option ${s.title === p.section ? "selected" : ""}>${s.title}</option>`).join("");
  const faces = FACE_NAMES[kind] || FACE_NAMES.I;
  const boltOpts = (b) => app.info.codes.bolts.map((x) => `<option ${x === b ? "selected" : ""}>${x}</option>`).join("") + `<option ${b === "custom" ? "selected" : ""} value="custom">other</option>`;
  const faceOpts = (f) => Object.entries(faces).map(([k, n]) => `<option value="${k}" ${k === f ? "selected" : ""}>${n} (${k})</option>`).join("");

  ed.innerHTML = `
  <div class="toolbar"><h2 style="margin:0 12px 0 0">Part ${esc(p.mark)}</h2>
    <button id="ed-nc1">Export NC1</button><button id="ed-step" title="The part as a solid for CAD (needs CadQuery on the computer running the app)">Export STEP</button><button id="ed-dup">Duplicate</button><button id="ed-del" class="danger">Delete</button>
    <span class="muted small">${fromFile ? "Shape from " + esc(p.source) : "Made here"}</span></div>
  <div class="grid">
    ${field("Mark", `<input data-k="mark" value="${esc(p.mark)}">`)}
    ${field("Family", `<select id="ed-fam">${famOpts}</select>`)}
    ${field("Section", `<select id="ed-sec">${sizeOpts || `<option>${esc(p.section)}</option>`}</select>`)}
    ${field("Length mm", num("length", p.length))}
    ${field("Quantity", num("qty", p.qty))}
    ${field("Grade (BS EN 10025-2)", `<select data-k="grade">${app.info.codes.grades.map((g) => `<option ${g === p.grade ? "selected" : ""}>${g}</option>`).join("")}</select>`)}
  </div>
  <div class="box"><h3>Holes and slots <span class="muted small">(BS EN 1090-2 hole sizes; x along the part, y across the face)</span></h3>
    <table><tr><th>#</th><th>Face</th><th>x</th><th>y</th><th>Bolt</th><th>Type</th><th>&Oslash; d</th><th>Slot</th><th></th></tr>
    ${p.holes.map((h, i) => `<tr data-h="${i}"><td>${i + 1}</td><td><select data-hk="face">${faceOpts(h.face === "h" ? "v" : h.face)}</select></td>
      <td><input type="number" data-hk="x" value="${+h.x.toFixed(1)}"></td><td class="nowrap"><input type="number" data-hk="y" value="${+h.y.toFixed(1)}"><button class="mini" data-centre="${i}" title="Put this hole on the centre line of its face">centre</button></td>
      <td><select data-hk="bolt">${boltOpts(h.bolt || guessBolt(h))}</select></td>
      <td><select data-hk="type">${app.info.codes.hole_types.map((t) => `<option ${t === (h.type || guessType(h)) ? "selected" : ""}>${t}</option>`).join("")}</select></td>
      <td><input type="number" data-hk="d" value="${h.d}" step="0.5"></td><td><input type="number" data-hk="slot" value="${h.slot || 0}"></td>
      <td><button data-del-hole="${i}" title="remove">&times;</button></td></tr>`).join("")}
    </table>
    <div class="toolbar"><button id="ed-add-hole">+ Hole</button>
      <span class="muted small">Bolt group:</span>
      <select id="grp-type"><option value="fin">Fin plate / end cleat holes (web)</option><option value="flange">Pair across a flange</option><option value="row">Row along the part</option></select>
      <select id="grp-bolt">${boltOpts(app.info.codes.standard_bolt)}</select>
      <label>n <input id="grp-n" type="number" value="3" min="1" style="width:60px"></label>
      <label>pitch <input id="grp-p" type="number" value="70" style="width:70px"></label>
      <label>at x <input id="grp-x" type="number" value="50" style="width:80px"></label>
      <select id="grp-end"><option value="start">from start</option><option value="end">from end</option><option value="both">both ends</option></select>
      <button id="grp-add" class="primary">Add group</button></div>
  </div>
  <div class="box"><h3>Notches (copes) <span class="muted small">${kind === "L" ? "not used on angles" : "size them to clear the supporting beam's flange (Blue Book N x n)"}</span></h3>
    ${fromFile ? '<div class="muted">The shape comes from the NC1 file - its notches and end cuts are used as they are.</div>' : `
    <table><tr><th>End</th><th>Side</th><th>Length N</th><th>Depth n</th><th>Radius</th><th></th></tr>
    ${p.copes.map((c, i) => `<tr data-c="${i}"><td><select data-ck="end"><option ${c.end === "start" ? "selected" : ""}>start</option><option ${c.end === "end" ? "selected" : ""}>end</option></select></td>
      <td><select data-ck="side"><option ${c.side === "top" ? "selected" : ""}>top</option><option ${c.side === "bottom" ? "selected" : ""}>bottom</option></select></td>
      <td><input type="number" data-ck="length" value="${c.length}"></td><td><input type="number" data-ck="depth" value="${c.depth}"></td>
      <td><input type="number" data-ck="radius" value="${c.radius ?? 10}"></td><td><button data-del-cope="${i}">&times;</button></td></tr>`).join("")}
    </table>
    <div class="toolbar">${kind === "L" ? "" : `<span class="muted small">To clear</span><select id="cope-sup">${["UB", "UC", "PFC"].flatMap((f) => app.sections[f].map((s) => `<option>${s.title}</option>`)).join("")}</select>
      <select id="cope-where"><option value="start">at start</option><option value="end">at end</option><option value="both" selected>both ends</option></select>
      <select id="cope-side"><option>top</option><option>bottom</option></select>
      <button id="cope-add" class="primary">Add notch</button>`}</div>`}
  </div>
  ${fromFile ? "" : `<div class="box"><h3>End cuts (mitres, degrees)</h3><div class="grid">
    ${field("Start - web", `<input type="number" data-m="start.web" value="${p.mitres?.start?.web || 0}">`)}
    ${field("Start - flange", `<input type="number" data-m="start.flange" value="${p.mitres?.start?.flange || 0}">`)}
    ${field("End - web", `<input type="number" data-m="end.web" value="${p.mitres?.end?.web || 0}">`)}
    ${field("End - flange", `<input type="number" data-m="end.flange" value="${p.mitres?.end?.flange || 0}">`)}</div></div>`}
  <div class="box"><h3>Checks (UK codes)</h3><div id="ed-checks" class="checks muted">checking&hellip;</div></div>
  <div class="box"><h3>Drawing</h3><div id="ed-drawing" class="drawing"></div></div>`;
  wireEditor(p, sec);
  scheduleCheck();
}

function guessBolt(h) {
  for (const b of app.info.codes.bolts) if (Math.abs(app.info.codes.hole_sizes[b].normal[0] - h.d) < 0.01) return b;
  return "custom";
}
function guessType(h) { return h.slot ? (h.slot - h.d > 0.9 * (h.d - 2) ? "long slot" : "short slot") : "normal"; }

function holeFor(bolt, type) {
  const [d, slot] = app.info.codes.hole_sizes[bolt][type];
  return { d, slot: slot || 0 };
}

function wireEditor(p, sec) {
  const ed = $("editor");
  const changed = (rebuild = false) => { p._errors = undefined; saveLocal(); if (rebuild) renderEditor(); else scheduleCheck(); jobChangedSoon(); };
  ed.querySelectorAll("[data-k]").forEach((el) => (el.onchange = () => {
    const k = el.dataset.k;
    p[k] = el.type === "number" ? +el.value : el.value;
    if (k === "qty") p.qty = Math.max(1, Math.round(p.qty));
    changed(k === "mark");
  }));
  $("ed-fam").onchange = (e) => { const first = app.sections[e.target.value][0]; p.section = first.title; p.custom = null; changed(true); };
  $("ed-sec").onchange = (e) => { p.section = e.target.value; p.custom = null; changed(true); };
  ed.querySelectorAll("tr[data-h]").forEach((tr) => {
    const h = p.holes[+tr.dataset.h];
    tr.querySelectorAll("[data-hk]").forEach((el) => (el.onchange = () => {
      const k = el.dataset.hk;
      if (k === "bolt" || k === "type") {
        h[k] = el.value;
        if ((h.bolt || "custom") !== "custom") Object.assign(h, holeFor(h.bolt, h.type || "normal"));
        if (!h.slot) delete h.slot;
        return changed(true);
      }
      h[k] = el.tagName === "SELECT" ? el.value : +el.value;
      changed();
    }));
  });
  ed.querySelectorAll("[data-centre]").forEach((b) => (b.onclick = () => {
    const h = p.holes[+b.dataset.centre];
    h.y = Math.round(faceCentre(p, sec, h.face, h.x) * 10) / 10;
    changed(true);
  }));
  ed.querySelectorAll("[data-del-hole]").forEach((b) => (b.onclick = () => { p.holes.splice(+b.dataset.delHole, 1); changed(true); }));
  ed.querySelectorAll("[data-del-cope]").forEach((b) => (b.onclick = () => { p.copes.splice(+b.dataset.delCope, 1); changed(true); }));
  ed.querySelectorAll("tr[data-c]").forEach((tr) => {
    const c = p.copes[+tr.dataset.c];
    tr.querySelectorAll("[data-ck]").forEach((el) => (el.onchange = () => { c[el.dataset.ck] = el.type === "number" ? +el.value : el.value; changed(); }));
  });
  ed.querySelectorAll("[data-m]").forEach((el) => (el.onchange = () => {
    const [end, k] = el.dataset.m.split(".");
    p.mitres = p.mitres || {};
    p.mitres[end] = p.mitres[end] || {};
    p.mitres[end][k] = +el.value;
    changed();
  }));
  $("ed-add-hole").onclick = () => {
    const face = sec.kind === "L" ? "v" : "v";
    p.holes.push(Object.assign({ face, x: Math.round(p.length / 2), y: Math.round(faceCentre(p, sec, face, p.length / 2) * 10) / 10, bolt: app.info.codes.standard_bolt, type: "normal" },
      holeFor(app.info.codes.standard_bolt, "normal")));
    changed(true);
  };
  $("grp-add").onclick = () => {
    const bolt = $("grp-bolt").value === "custom" ? app.info.codes.standard_bolt : $("grp-bolt").value;
    const { d } = holeFor(bolt, "normal");
    const n = Math.max(1, +$("grp-n").value), pitch = +$("grp-p").value, x0 = +$("grp-x").value, where = $("grp-end").value;
    const type = $("grp-type").value;
    const ends = where === "both" ? ["start", "end"] : [where];
    for (const end of ends) {
      const X = (dx) => (end === "start" ? x0 + dx : p.length - x0 - dx);
      if (type === "fin") {            // a vertical line of holes in the web, below any top notch
        const mid = webCentre(p, sec, X(0));             // centred on the web left below any notch
        for (let i = 0; i < n; i++) p.holes.push({ face: "v", x: X(0), y: Math.round((mid + ((n - 1) / 2 - i) * pitch) * 10) / 10, d, bolt, type: "normal" });
      } else if (type === "flange") {  // pairs across the top flange at UK cross-centres
        const cc = sec.kind === "I" ? ((sec.b || 150) > 180 ? 140 : 90) : Math.round((sec.b || 90) / 2);
        for (let i = 0; i < n; i++) {
          if (sec.kind === "I") for (const s of [-1, 1]) p.holes.push({ face: "o", x: X(i * pitch), y: sec.b / 2 + (s * cc) / 2, d, bolt, type: "normal" });
          else p.holes.push({ face: sec.kind === "L" ? "u" : "o", x: X(i * pitch), y: cc, d, bolt, type: "normal" });
        }
      } else {
        for (let i = 0; i < n; i++) p.holes.push({ face: "v", x: X(i * pitch), y: Math.round(webCentre(p, sec, X(i * pitch)) * 10) / 10, d, bolt, type: "normal" });
      }
    }
    changed(true);
  };
  if ($("cope-add")) $("cope-add").onclick = () => {
    const sup = sectionOf($("cope-sup").value);
    const N = sup.N || Math.round(sup.b / 2 + 10), depth = sup.n || Math.ceil(sup.tf + sup.r);
    const where = $("cope-where").value, side = $("cope-side").value;
    for (const end of where === "both" ? ["start", "end"] : [where]) {
      p.copes = p.copes.filter((c) => !(c.end === end && c.side === side));
      p.copes.push({ end, side, length: N, depth: Math.max(depth, Math.ceil((sec.tf || 10) + (sec.r || 10))), radius: app.info.codes.cope_radius });
    }
    changed(true);
  };
  $("ed-nc1").onclick = async () => download(`${p.mark}.nc1`, await post("/api/nc1/export", { part: clean(p) }, true));
  $("ed-step").onclick = async () => {
    try { const r = await post("/api/cad/part", { part: clean(p) }); download(r.name, r.step, "application/step"); }
    catch (e) { toast(e.message, true); }
  };
  $("ed-dup").onclick = () => {
    const copy = JSON.parse(JSON.stringify(p));
    copy.mark = p.mark + "-2";
    app.job.parts.splice(selected + 1, 0, copy);
    selected++;
    jobChanged().then(renderEditor);
  };
  $("ed-del").onclick = () => {
    if (!confirm(`Delete part ${p.mark}?`)) return;
    app.job.parts.splice(selected, 1);
    selected = Math.max(0, selected - 1);
    jobChanged().then(renderEditor);
  };
}

function notchDepth(p, end, side) {
  const c = (p.copes || []).find((x) => x.end === end && x.side === side);
  return c ? c.depth : 0;
}

// Middle of the web that is left at x: between the flanges (plus root radius) or a notch.
// Holes go here unless the drawing says otherwise.
function webCentre(p, sec, x) {
  const root = (sec.tf || 10) + (sec.r || 0);
  const end = x < p.length / 2 ? "start" : "end";
  const cope = (side) => (p.copes || []).find((c) => c.end === end && c.side === side && (end === "start" ? x <= c.length + 200 : x >= p.length - c.length - 200));
  const lo = Math.max(root, cope("bottom") ? cope("bottom").depth : 0);
  const hi = (sec.h || 200) - Math.max(root, cope("top") ? cope("top").depth : 0);
  return (lo + hi) / 2;
}

function faceCentre(p, sec, face, x) {
  if (face === "v" || face === "h") return sec.kind === "L" ? 50 : webCentre(p, sec, x);
  return (sec.b || 100) / 2;
}

const clean = (p) => Object.fromEntries(Object.entries(p).filter(([k]) => !k.startsWith("_")));

let nestTimer = null;
function jobChangedSoon() { clearTimeout(nestTimer); nestTimer = setTimeout(() => jobChanged(), 600); }

function scheduleCheck() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(runCheck, 250);
}

async function runCheck() {
  const p = app.job.parts[selected];
  if (!p) return;
  try {
    const v = await post("/api/part", { part: clean(p) });
    lastView = v;
    p._weight = v.weight / p.qty;
    p._errors = v.checks.some((c) => c.level === "error");
    const box = $("ed-checks");
    if (!box) return;
    box.classList.remove("muted");
    box.innerHTML = v.checks.length
      ? v.checks.map((c) => `<div class="${c.level}"><b>${esc(c.item)}</b>: ${esc(c.text)} ${c.ref ? `<span class="ref">- ${esc(c.ref)}</span>` : ""}</div>`).join("")
      : `<div class="ok">&#10003; Passes the UK checks (BS EN 1090-2 hole sizes, BS EN 1993-1-8 edge/end distances and spacing, notch rules). ${v.weight.toFixed(1)} kg each.</div>`;
    drawPart(v);
    renderPartList();
  } catch (e) {
    const box = $("ed-checks");
    if (box) box.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

// ---------------------------------------------------------------- 2D drawing
function drawPart(v) {
  const el = $("ed-drawing");
  if (!el) return;
  const p = v.part, sec = v.section, L = p.length;
  const kind = sec.kind;
  const order = kind === "L" ? ["v", "u"] : ["o", "v", "u"];
  const W = 1000, pad = 40, sx = (W - 2 * pad) / L;
  const scaleY = Math.min(sx * 3.5, 0.9);
  let y = 18, out = "";
  const errHoles = new Set(v.checks.filter((c) => c.level === "error" && /^hole \d+$/.test(c.item)).map((c) => +c.item.split(" ")[1] - 1));
  for (const face of order) {
    const poly = v.faces[face];
    if (!poly) continue;
    const Wf = face === "v" ? sec.h : sec.b;
    const hgt = Wf * scaleY;
    const X = (x) => pad + x * sx, Y = (yy) => y + hgt - yy * scaleY;
    out += `<text x="4" y="${y + hgt / 2 + 4}" font-size="11" fill="#66717c">${face}</text>`;
    out += `<text x="${pad}" y="${y - 4}" font-size="11" fill="#66717c">${(FACE_NAMES[kind] || FACE_NAMES.I)[face] || face}</text>`;
    out += `<polygon points="${poly.map(([a, b]) => `${X(a)},${Y(b)}`).join(" ")}" fill="#e3e8ed" stroke="#33404c" stroke-width="1.2"/>`;
    p.holes.forEach((h, i) => {
      const hf = h.face === "h" ? "v" : (kind === "L" && h.face !== "v" ? "u" : h.face);
      if (hf !== face) return;
      const o = holeOutline(h, 24);
      out += `<polygon points="${o.map(([a, b]) => `${X(a)},${Y(b)}`).join(" ")}" fill="${errHoles.has(i) ? "#f2b8b5" : "#fff"}" stroke="${errHoles.has(i) ? "#c62828" : "#1f6fb2"}" stroke-width="1.4"><title>hole ${i + 1}: x ${h.x} y ${h.y} d ${h.d}</title></polygon>`;
      out += `<text x="${X(h.x) + 4}" y="${Y(h.y) - 4}" font-size="9" fill="#1f6fb2">${i + 1}</text>`;
    });
    (p.inner || []).forEach((it) => {
      const f = it.face === "h" ? "v" : it.face;
      if (f === face) out += `<polygon points="${it.points.map(([a, b]) => `${X(a)},${Y(b)}`).join(" ")}" fill="#fff" stroke="#1f6fb2"/>`;
    });
    y += hgt + 30;
  }
  out += `<line x1="${pad}" x2="${pad + L * sx}" y1="${y - 10}" y2="${y - 10}" stroke="#33404c"/>` +
    `<text x="${pad + (L * sx) / 2}" y="${y + 4}" font-size="12" text-anchor="middle">${L.toFixed(0)} mm &middot; ${esc(p.section)} &middot; ${v.weight.toFixed(1)} kg</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${y + 12}">${out}</svg>`;
}

// ---------------------------------------------------------------- set up
export async function initParts() {
  $("btn-add-part").onclick = () => { app.job.parts.push(newPart()); selected = app.job.parts.length - 1; jobChanged().then(renderEditor); };
  $("file-nc1").onchange = (e) => importFiles([...e.target.files]).then(() => (e.target.value = ""));
  const dz = $("drop-zone");
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); importFiles([...e.dataTransfer.files]); };
  const ex = $("example-pick");
  for (const name of await get("/api/examples")) ex.add(new Option(name, name));
  ex.onchange = async () => {
    if (!ex.value) return;
    const v = await get("/api/examples/" + ex.value);
    addPart(v);
    $("import-report").innerHTML = `<h3>Import report</h3><div><b>${esc(ex.value)}</b>: ${v.report.map(esc).join(" &middot; ")}</div>`;
    ex.value = "";
    await jobChanged();
    renderEditor();
  };
  $("btn-save-job").onclick = async () => {
    const name = $("job-name").value.trim() || "job";
    await post("/api/jobs/" + encodeURIComponent(name), { stock_length: app.job.stock_length, parts: app.job.parts.map(clean) });
    toast(`Saved job "${name}" (jobs/${name}.json)`);
    refreshJobs();
  };
  $("job-open").onchange = async (e) => {
    if (!e.target.value) return;
    app.job = await get("/api/jobs/" + encodeURIComponent(e.target.value));
    $("job-name").value = e.target.value;
    $("stock-length").value = app.job.stock_length;
    e.target.value = "";
    selected = 0;
    await jobChanged();
    renderEditor();
  };
  $("btn-clear-job").onclick = () => { if (confirm("Remove every part from this job?")) { app.job.parts = []; jobChanged().then(renderEditor); } };
  refreshJobs();
  renderEditor();
}

async function refreshJobs() {
  const sel = $("job-open");
  sel.length = 1;
  for (const j of await get("/api/jobs")) sel.add(new Option(j, j));
}
