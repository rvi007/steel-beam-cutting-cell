// The Sensors tab: every sensor (simulated until it is wired in), the bar check, the stops with
// what each hand does, and the plasma cut chart.
import { get, post } from "./api.js";
import { toast } from "./app.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// the stops the screen can simulate, and the sensor input behind each
export const SIMULATE = { OBJECT: "bed_clear", LOAD: "load_secure", TORCH: "torch_ok", FIRE: "no_fire" };

async function renderSensors() {
  const { sensors, decisions } = await get("/api/sensors");
  let html = "", group = "";
  for (const s of sensors) {
    if (s.group !== group) {
      if (group) html += "</tbody></table>";
      group = s.group;
      html += `<div class="sn-group">${esc(s.group_name)}</div><table class="list sn"><tbody>`;
    }
    const cls = s.state === "connected" ? "good" : s.state === "simulated" ? "sim" : s.state === "not fitted" ? "off" : "warn";
    html += `<tr><td style="width:26%"><b>${esc(s.name)}</b>${s.safety_rated ? '<br><span class="tag good">safety-rated</span>' : ""}</td>
      <td class="what">${esc(s.what)}<br><span class="muted small">Where: ${esc(s.where)} &middot; ${esc(s.interface)}</span>
      <br><span class="muted small">Buy: ${esc(s.buy)}</span></td>
      <td style="width:90px"><span class="tag ${cls}">${esc(s.state)}</span></td></tr>`;
  }
  $("sn-list").innerHTML = html + "</tbody></table>";
  $("sn-decisions").innerHTML = `<table class="list sn"><thead><tr><th>Stop</th><th>Category</th><th>Cutter</th><th>Handler</th><th>You</th><th></th></tr></thead><tbody>` +
    decisions.map((d) => `<tr><td><b>${esc(d.text)}</b><br><span class="muted small">${esc(d.ref)}</span></td>
      <td><span class="tag cat${d.category}">${d.category}</span></td>
      <td>${esc(d.cutter)}</td><td>${esc(d.handler)}</td><td>${esc(d.you)}</td>
      <td>${SIMULATE[d.code] ? `<button class="mini" data-sim="${d.code}">Simulate</button>` : ""}</td></tr>`).join("") +
    `</tbody></table><p class="muted small">Category 0: power cut at once. 1: controlled stop, then power off. 2: controlled stop,
      power kept on - the hands hold their position and the magnet keeps its grip (BS EN 60204-1).</p>`;
  for (const b of document.querySelectorAll("[data-sim]")) b.onclick = async () => {
    await post("/api/safety/input", { name: SIMULATE[b.dataset.sim], value: false });
    toast(`Simulated: ${b.closest("tr").querySelector("b").textContent} - see the Safety tab; set the sensor back there, then Reset`);
  };
}

export function barCheckHtml(r) {
  if (!r) return "";
  if (r.error) return `<div class="bad">&#10008; ${esc(r.error)}</div>`;
  return `<div class="${r.ok ? "good" : "bad"}"><b>${r.ok ? "&#10004;" : "&#10008;"} ${esc(r.result)}</b></div>
    <div class="small">Start at x = <b>${r.start_x} mm</b> &middot; end at x = ${r.end_x} mm &middot; length <b>${r.length} mm</b>
      ${r.simulated ? '<span class="tag sim">simulated readings</span>' : ""}</div>
    <table class="list pl"><thead><tr><th>Check</th><th>Measured</th><th>Nominal</th><th>Allowed</th><th></th></tr></thead><tbody>
    ${r.checks.map((c) => `<tr><td>${esc(c.what)}</td><td>${c.measured}</td><td>${c.nominal}</td><td>${esc(c.allowed)}</td>
      <td>${c.ok ? '<span class="good">OK</span>' : '<span class="bad">OUT</span>'}</td></tr>`).join("")}</tbody></table>
    <div class="muted small">${esc(r.standard)} rolling tolerances. Every cut is moved by ${r.offsets.x_mm} mm along the bar.</div>
    <ol class="sn-steps">${r.how.map((h) => `<li>${esc(h)}</li>`).join("")}</ol>`;
}

async function measure() {
  try {
    const r = await post("/api/sensors/measure", { section: $("sn-section").value.trim(), length: +$("sn-length").value });
    $("sn-bar").innerHTML = barCheckHtml(r);
  } catch (e) { $("sn-bar").innerHTML = `<div class="bad">${esc(e.message)}</div>`; }
}

async function renderPlasma(proc) {
  const t = await get("/api/plasma" + (proc ? "?process=" + proc : ""));
  const sel = $("sn-process");
  if (!sel.length) {
    for (const [k, label] of Object.entries(t.processes)) sel.add(new Option(label + (k === t.current ? " (in use)" : ""), k));
    sel.value = t.current;
    sel.onchange = () => renderPlasma(sel.value);
  }
  const steps = t.process === "pen" ? `<ol class="sn-steps"><li>Z moves down until the pen holder's switch closes (touch-off).</li>
      <li>The pen draws every cut line; the sprung holder keeps light, even pressure.</li></ol>`
    : `<ol class="sn-steps">
      <li><b>Touch-off</b> (initial height sensing): the nozzle touches the steel and closes a small circuit - that is the real surface.</li>
      <li>Lift to the <b>pierce height</b> (about 2x cut height), fire, wait the <b>pierce delay</b> - or <b>edge start</b> from a flange edge, no pierce.</li>
      <li>Drop to the <b>cut height</b> and move at the <b>cut speed</b>.</li>
      <li><b>Torch height control</b> holds the <b>arc voltage</b> (higher torch = higher voltage) - OFF on holes, corners and near edges.</li>
      <li>Holes: slower, pierce in the centre, lead-in arc. Smaller than the plate is thick (d/t &lt; 1): drill them.</li></ol>`;
  $("sn-plasma").innerHTML = steps + `<table class="list pl"><thead><tr><th>Plate</th><th>Cut</th><th>Amps</th><th>Speed<br>mm/min</th>
      <th>Arc V</th><th>Cut / pierce<br>height mm</th><th>Pierce<br>s</th><th>Kerf<br>mm</th><th>THC</th></tr></thead><tbody>` +
    t.rows.map((r) => `<tr><td>${r.thickness_mm}</td><td>${esc(r.feature)}</td><td>${r.amps || "-"}</td><td>${r.speed_mm_min}</td>
      <td>${r.arc_voltage_v || "-"}</td><td>${r.cut_height_mm} / ${r.pierce_height_mm}</td><td>${r.pierce_delay_s}</td><td>${r.kerf_mm}</td>
      <td>${esc(r.thc.split(" ")[0])}</td></tr>`).join("") +
    `</tbody></table><p class="muted small">${esc(t.label)}. <b>Typical values for planning</b> - put the cut chart of your own plasma
      system and consumables in beamcell/plasma.py and qualify the process (BS EN ISO 9013, BS EN 1090-2) before cutting real steel.
      The cut chart in use is set in config/cell.toml ([plasma] process).</p>`;
}

export function initSensors() {
  $("sn-measure").onclick = measure;
  let loaded = false;
  document.querySelector(".tabs button[data-tab=sensors]").addEventListener("click", () => {
    renderSensors();
    if (!loaded) { loaded = true; renderPlasma(); measure(); }
  });
}
