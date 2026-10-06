// The Plasma tab: try settings on the real machine, save the ones that cut well (one file per beam
// in plasma_settings/), and open them again when the same beam is cut. The Machine tab's
// "Plasma settings" list picks which saved file the plan uses (or the cut chart).
import { get, post } from "./api.js";
import { app, toast, clearPlan } from "./app.js";
import { manual } from "./manual.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const RATE_CLASS = { good: "good", try: "warn", bad: "badtag" };

const pz = { meta: null, list: [], edit: null, chart: null, loadedName: "", dirty: false };

async function loadMeta() {
  const m = await get("/api/plasma/presets");
  pz.meta = m;
  pz.list = m.presets;
  return m;
}

// ---------------------------------------------------------------- the list of saved settings
function renderList() {
  const q = $("pz-search").value.trim().toLowerCase();
  const rows = pz.list.filter((p) => !q || (p.name + " " + p.section + " " + p.grade).toLowerCase().includes(q));
  $("pz-count").textContent = pz.list.length ? `(${pz.list.length})` : "";
  $("pz-list").innerHTML = rows.length ? rows.map((p) => `
    <button class="pz-item ${p.name === pz.loadedName ? "on" : ""}" data-pz="${esc(p.name)}">
      <span class="pz-name">${esc(p.name)}</span>
      <span class="tag ${RATE_CLASS[p.rating] || ""}">${esc(pz.meta.ratings[p.rating] || p.rating)}</span>
      <span class="muted small">${esc(p.section)} &middot; web ${p.web_mm} / flange ${p.flange_mm} mm &middot; ${esc(p.updated)}</span>
    </button>`).join("")
    : `<div class="muted small empty">${pz.list.length ? "Nothing matches." : "No saved settings yet. Start new settings above, try them on a test piece, then Save."}</div>`;
  for (const b of document.querySelectorAll("[data-pz]")) b.onclick = () => openPreset(b.dataset.pz);
}

async function openPreset(name) {
  if (pz.dirty && !confirm("You have changes that aren't saved. Open another file anyway?")) return;
  pz.edit = await get("/api/plasma/presets/" + encodeURIComponent(name));
  pz.loadedName = name;
  pz.dirty = false;
  await loadChart();
  renderEditor();
  renderList();
}

async function loadChart() {
  pz.chart = null;
  if (!pz.edit || !pz.edit.section) return;
  try {
    pz.chart = await get(`/api/plasma/start?section=${encodeURIComponent(pz.edit.section)}&process=${pz.edit.process}&grade=${encodeURIComponent(pz.edit.grade)}`);
  } catch (e) { /* not a library section: no chart to compare with */ }
}

async function startNew() {
  if (pz.dirty && !confirm("You have changes that aren't saved. Start new settings anyway?")) return;
  const section = $("pz-section").value.trim();
  try {
    pz.edit = await get(`/api/plasma/start?section=${encodeURIComponent(section)}&process=${$("pz-process").value}&grade=${$("pz-grade").value}`);
  } catch (e) { return toast(`"${section}" isn't a section in the library - pick one from the list`, true); }
  pz.chart = JSON.parse(JSON.stringify(pz.edit));
  pz.loadedName = "";
  pz.dirty = true;
  renderEditor();
  renderList();
  toast("Filled in from the cut chart - adjust, try on a test piece, then Save");
}

// ---------------------------------------------------------------- the editor
function renderEditor() {
  const e = pz.edit, m = pz.meta;
  if (!e) {
    $("pz-editor").innerHTML = `<div class="pz-empty"><h2>Plasma settings</h2>
      <p>Plasma doesn't always cut the same way. The cut chart is only a starting point: every machine, set of consumables,
        gas supply and batch of steel behaves a bit differently.</p>
      <ol><li><b>Start new settings</b> for a beam (left). The numbers are filled in from the cut chart.</li>
        <li>Cut a test piece. Change the numbers until the cut is clean: square edges, little dross, holes the right size.</li>
        <li>Mark it <b>Works well</b> and <b>Save</b>. It's saved as a file named after the beam, in <code>plasma_settings/</code>.</li>
        <li>Next time you cut that beam, the Machine tab picks the saved settings for it automatically.</li></ol></div>`;
    return;
  }
  const chartRow = (part, key) => pz.chart && pz.chart[part] ? pz.chart[part][key] : "";
  const rows = Object.entries(m.fields).map(([key, [label, unit, lo, hi]]) => {
    const cell = (part) => {
      const v = e[part][key], c = chartRow(part, key);
      const diff = c !== "" && Number(v) !== Number(c);
      return `<td><input type="number" step="any" min="${lo}" max="${hi}" data-part="${part}" data-key="${key}" value="${esc(v)}"
        class="${diff ? "changed" : ""}" ${key === "thickness_mm" ? 'title="the steel thickness this row is for"' : ""}>
        ${c !== "" ? `<span class="chart-val" title="cut chart">${esc(c)}</span>` : ""}</td>`;
    };
    return `<tr><th>${esc(label)} <span class="muted small">${esc(unit)}</span></th>${cell("web")}${cell("flange")}</tr>`;
  }).join("");
  const thc = (part) => `<td><select data-part="${part}" data-key="thc">${["on", "off"].map((v) =>
    `<option ${e[part].thc === v ? "selected" : ""}>${v}</option>`).join("")}</select></td>`;
  $("pz-editor").innerHTML = `
    <div class="pz-head">
      <div>
        <h2>${pz.loadedName ? esc(pz.loadedName) : "New settings"} ${pz.dirty ? '<span class="tag warn">not saved</span>' : '<span class="tag good">saved</span>'}</h2>
        <div class="muted small">${pz.loadedName ? `plasma_settings/${esc(pz.loadedName)}.json &middot; saved ${esc(e.updated || "")}` : "Not saved yet"}</div>
      </div>
      <div class="toolbar">
        <button id="pz-save" class="primary">Save</button>
        <button id="pz-saveas">Save as&hellip;</button>
        <button id="pz-use" title="Use these settings for the job on the Machine tab">Use on the Machine tab</button>
        <button id="pz-chart" title="Put the cut chart's numbers back">Reset to the cut chart</button>
        ${pz.loadedName ? '<button id="pz-del" class="danger">Delete</button>' : ""}
      </div>
    </div>
    <div class="box grid pz-fields">
      <label class="f">Name (the file name)<input id="pz-name" value="${esc(e.name)}"></label>
      <label class="f">Beam (section)<input id="pz-f-section" value="${esc(e.section)}" list="pz-sections"></label>
      <label class="f">Grade<select id="pz-f-grade">${m.grades.map((g) => `<option ${g === e.grade ? "selected" : ""}>${g}</option>`).join("")}</select></label>
      <label class="f">Plasma<select id="pz-f-process">${Object.entries(m.processes).map(([k, l]) =>
        `<option value="${k}" ${k === e.process ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
      <label class="f">Consumables (nozzle, shield, electrode)<input id="pz-f-consumables" value="${esc(e.consumables)}" placeholder="e.g. 130 A mild steel set, nozzle 220646"></label>
      <label class="f">Gas<input id="pz-f-gas" value="${esc(e.gas)}"></label>
    </div>
    <div class="box">
      <h3>How well it cuts</h3>
      <div class="seg-toggle rating">${Object.entries(m.ratings).map(([k, l]) =>
        `<button data-rate="${k}" class="${e.rating === k ? "on " + k : ""}">${esc(l)}</button>`).join("")}</div>
      <label class="f">Notes: what you tried, what the cut looked like
        <textarea id="pz-f-notes" rows="3" class="full" placeholder="e.g. dross on the bottom edge at 3000 mm/min - 3300 cleaner; holes 0.3 mm small">${esc(e.notes)}</textarea></label>
    </div>
    <div class="box">
      <h3>Settings <span class="muted small">web and flange are different thicknesses, so each has its own column.
        <span class="chart-val">grey</span> = the cut chart's value; changed numbers are highlighted.</span></h3>
      <table class="pz-table"><thead><tr><th></th><th>Web</th><th>Flange</th></tr></thead>
        <tbody>${rows}<tr><th>Torch height control <span class="muted small">THC</span></th>${thc("web")}${thc("flange")}</tr></tbody></table>
      <p class="muted small">Holes always cut with torch height control off, at the hole speed. Corners and radii slow down to the corner speed.
        Edge starts don't pierce, so they skip the pierce delay.</p>
    </div>`;
  const touch = () => { if (!pz.dirty) { pz.dirty = true; renderHeadOnly(); } };
  for (const inp of $("pz-editor").querySelectorAll("[data-part]")) inp.oninput = inp.onchange = () => {
    e[inp.dataset.part][inp.dataset.key] = inp.dataset.key === "thc" ? inp.value : inp.value === "" ? "" : Number(inp.value);
    const c = chartRow(inp.dataset.part, inp.dataset.key);
    inp.classList.toggle("changed", c !== "" && inp.dataset.key !== "thc" && Number(inp.value) !== Number(c));
    touch();
  };
  const field = (id, key) => { $(id).oninput = $(id).onchange = () => { e[key] = $(id).value; touch(); }; };
  field("pz-name", "name"); field("pz-f-section", "section"); field("pz-f-grade", "grade");
  field("pz-f-consumables", "consumables"); field("pz-f-gas", "gas"); field("pz-f-notes", "notes");
  $("pz-f-process").onchange = async () => { e.process = $("pz-f-process").value; touch(); await loadChart(); renderEditor(); };
  $("pz-f-section").onchange = async () => { e.section = $("pz-f-section").value.trim(); touch(); await loadChart(); renderEditor(); };
  for (const b of $("pz-editor").querySelectorAll("[data-rate]")) b.onclick = () => { e.rating = b.dataset.rate; touch(); renderEditor(); };
  $("pz-save").onclick = () => save(e.name);
  $("pz-saveas").onclick = () => {
    const n = prompt("Save as (a new file):", e.name + " v2");
    if (n) save(n);
  };
  $("pz-use").onclick = async () => {
    if (pz.dirty && !(await save(e.name))) return;
    usePreset(pz.loadedName);
    document.querySelector('.tabs button[data-tab="cell"]').click();
    toast(`The Machine tab now uses "${pz.loadedName}" - press Plan`);
  };
  $("pz-chart").onclick = () => {
    if (!pz.chart) return toast("No cut chart for this beam", true);
    e.web = { ...pz.chart.web }; e.flange = { ...pz.chart.flange };
    pz.dirty = true;
    renderEditor();
  };
  if ($("pz-del")) $("pz-del").onclick = async () => {
    if (!confirm(`Delete the saved settings "${pz.loadedName}"? The file is removed and can't be brought back.`)) return;
    await post("/api/plasma/presets-delete/" + encodeURIComponent(pz.loadedName), {});
    if (app.plasma === pz.loadedName) usePreset("");
    toast(`Deleted "${pz.loadedName}"`);
    pz.edit = null; pz.loadedName = ""; pz.dirty = false;
    await loadMeta(); renderList(); renderEditor(); refreshPlasmaPick();
  };
}

function renderHeadOnly() {
  const h = $("pz-editor").querySelector(".pz-head h2 .tag");
  if (h) { h.className = "tag warn"; h.textContent = "not saved"; }
}

async function save(name) {
  const e = pz.edit;
  const exists = pz.list.some((p) => p.name === name.trim());
  if (exists && name.trim() !== pz.loadedName && !confirm(`"${name}" already exists. Replace it?`)) return false;
  try {
    const saved = await post("/api/plasma/presets", { ...e, name });
    pz.edit = saved; pz.loadedName = saved.name; pz.dirty = false;
    await loadMeta(); await loadChart();
    renderEditor(); renderList(); refreshPlasmaPick();
    toast(`Saved plasma_settings/${saved.name}.json`);
    return true;
  } catch (err) { toast("Not saved: " + err.message, true); return false; }
}

// ---------------------------------------------------------------- the Machine tab's choice
function currentSection() {
  if (manual.on) return manual.job.section;
  const b = app.bars && app.bars[app.barIndex];
  return b ? b.section : "";
}

export function usePreset(name) {
  if ((app.plasma || "") === name) return;
  app.plasma = name;
  try { localStorage.setItem("plasma", name); } catch (e) { /* blocked */ }
  if (app.plan && !app.playing) clearPlan();
  refreshPlasmaPick();
}

let lastSection = null;
export async function refreshPlasmaPick() {
  const sel = $("plasma-pick");
  if (!sel || !pz.meta) return;
  const section = currentSection();
  const mine = pz.list.filter((p) => p.section === section).sort((a, b) => (a.rating === "good" ? -1 : 0) - (b.rating === "good" ? -1 : 0));
  const others = pz.list.filter((p) => p.section !== section);
  // a new beam: pick its best saved settings (works well first), or the cut chart if it has none
  if (section !== lastSection) {
    lastSection = section;
    const keep = mine.some((p) => p.name === app.plasma);
    if (!keep) {
      const best = mine.find((p) => p.rating === "good") || null;
      app.plasma = best ? best.name : "";
      if (app.plan && !app.playing && app.plan.process && (app.plan.process.preset || "") !== app.plasma) clearPlan();
    }
  }
  if (app.plasma && !pz.list.some((p) => p.name === app.plasma)) app.plasma = "";
  const opt = (p) => `<option value="${esc(p.name)}" ${p.name === app.plasma ? "selected" : ""}>${esc(p.name)} - ${esc(pz.meta.ratings[p.rating] || "")}</option>`;
  sel.innerHTML = `<option value="" ${!app.plasma ? "selected" : ""}>Cut chart (no saved settings)</option>` +
    (mine.length ? `<optgroup label="Saved for ${esc(section)}">${mine.map(opt).join("")}</optgroup>` : "") +
    (others.length ? `<optgroup label="Other beams">${others.map(opt).join("")}</optgroup>` : "");
  const chosen = pz.list.find((p) => p.name === app.plasma);
  $("plasma-pick-note").innerHTML = chosen
    ? (chosen.section === section ? `<span class="good">&#10004; Saved settings for this beam</span>` : `<span class="warn">&#9888; Saved for ${esc(chosen.section)}, not ${esc(section)}</span>`)
    : (mine.length ? "This beam has saved settings - pick one" : section ? `No saved settings for ${esc(section)} yet (Plasma tab)` : "");
}

export async function initPlasma() {
  try { app.plasma = localStorage.getItem("plasma") || ""; } catch (e) { app.plasma = ""; }
  const m = await loadMeta();
  for (const [k, l] of Object.entries(m.processes)) $("pz-process").add(new Option(l, k));
  $("pz-process").value = m.current;
  for (const g of m.grades) $("pz-grade").add(new Option(g, g));
  $("pz-grade").value = "S355";
  const dl = $("pz-sections");
  for (const rows of Object.values(app.sections)) for (const s of rows) if (s.cuttable) dl.append(new Option(s.title));
  $("pz-new").onclick = startNew;
  $("pz-search").oninput = renderList;
  $("plasma-pick").onchange = (e) => usePreset(e.target.value);
  document.querySelector('.tabs button[data-tab="plasma"]').addEventListener("click", async () => {
    if (!$("pz-section").value) $("pz-section").value = currentSection() || "UB 305x165x40";
    await loadMeta(); renderList();
    if (!pz.edit) renderEditor();
  });
  document.querySelector('.tabs button[data-tab="cell"]').addEventListener("click", refreshPlasmaPick);
  renderList();
  renderEditor();
  refreshPlasmaPick();
}
