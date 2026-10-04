// Safety in the browser: talks to the safety controller on the server (beamcell/safety.py),
// which alone decides whether the machine may move. This page:
//   - checks in 5 times a second (the server's watchdog stops the machine if it goes quiet),
//   - stops the 3D machine itself if the server stops answering (fail-safe both ways),
//   - shows the E-stop, Reset / Start, modes, checklist, inputs, stack light and event log,
//   - holds the Manual-mode enable (hold-to-run) while the button is held down.
import { get, post } from "./api.js";
import { app, toast } from "./app.js";

const $ = (id) => document.getElementById(id);
const client = Math.random().toString(36).slice(2, 10);
export const safety = { status: null, lastAnswer: 0, holding: false, estopLocal: false };

export function connected() { return performance.now() - safety.lastAnswer < 1000; }

const STATE_TEXT = {
  ESTOP: ["EMERGENCY STOP", "bad"], FAULT: ["PROTECTIVE STOP", "bad"], NOT_RESET: ["PRESS RESET", "warn"],
  READY: ["READY", "ok"], PAUSED: ["PAUSED", "warn"], RUNNING: ["RUNNING", "ok"], ISOLATED: ["ISOLATED - MAINTENANCE", "warn"],
};

async function act(action, body = {}) {
  try {
    const st = await post("/api/safety/" + action, Object.assign({ who: "screen" }, body));
    accept(st);
    if (st.ok === false) toast(`${action[0].toUpperCase() + action.slice(1)} refused: ${st.why.join("; ")}`, true);
    return st;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

export async function estop() {
  safety.estopLocal = true;                 // stop the picture at once, don't wait for the server
  app.playing = false;
  await act("estop", { source: "screen" });
}
export const startMachine = () => act("start");
export const stopMachine = (reason) => act("stop", { reason });
export const jobFinished = (details) => act("finished", { details });
// every planned job is registered with the safety controller: each one needs its own checklist
export const loadJob = (name) => act("job", { name });
export const clearSafetyJob = (details) => act("clear-job", { details });

function accept(st) {
  safety.status = st;
  safety.lastAnswer = performance.now();
  if (!st.estop_pressed) safety.estopLocal = false;
  app.playing = st.state === "RUNNING";
  render(st);
}

async function tick() {
  try {
    accept(await post("/api/safety/tick", { client, enable: safety.holding, playback: app.playbackFacts() }));
  } catch (e) { /* no answer: connected() goes false and the machine stops */ }
}

// ---------------------------------------------------------------- drawing
function render(st) {
  const [text, cls] = STATE_TEXT[st.state] || [st.state, ""];
  const why = st.latched.map((f) => `${f.text} (${f.ref})`).concat(
    st.state === "ESTOP" || st.state === "FAULT" || st.state === "NOT_RESET" ? st.reset_blockers.map((b) => "Before Reset: " + b) : []);
  // header
  const pill = $("pill-safety");
  pill.textContent = "Safety: " + text.toLowerCase();
  pill.className = "pill " + (cls === "bad" ? "bad" : cls === "ok" ? "ok" : "");
  const eb = $("btn-estop");
  eb.classList.toggle("pressed", st.estop_pressed);
  eb.textContent = st.estop_pressed ? "PRESSED" : "E-STOP";
  // stack light (on screen and in 3D)
  for (const c of ["red", "amber", "green", "blue"]) $("lamp-" + c).classList.toggle("on", !!st.lamps[c]);
  if (app.scene && app.scene.setSafety) app.scene.setSafety(st);
  // banner on the machine view
  const banner = $("safety-banner");
  const show = ["ESTOP", "FAULT", "NOT_RESET", "ISOLATED"].includes(st.state) || !connected();
  banner.hidden = !show;
  banner.classList.toggle("amber", st.state === "NOT_RESET" || st.state === "ISOLATED");
  $("safety-title").textContent = !connected() ? "NO CONNECTION TO THE SAFETY CONTROLLER" : text;
  $("safety-detail").textContent = why.join(" · ") || (st.state === "NOT_RESET" ? "Press Reset, confirm the checklist, then Start." : "");
  $("btn-release").hidden = !st.estop_pressed;
  $("btn-safety-reset").hidden = st.state === "ISOLATED";
  $("btn-hold").hidden = st.mode !== "MANUAL";
  // safety tab
  const s = $("sf-state");
  s.textContent = text + (st.mode !== "AUTO" ? ` · ${st.mode}` : "") + (st.state === "RUNNING" && st.speed_factor < 1 ? ` · ${Math.round(st.speed_factor * 100)}% speed` : "");
  s.className = "sf-state " + cls;
  $("sf-why").innerHTML = why.map((w) => `<div>&#9888; ${w}</div>`).join("") +
    (st.stop_category != null && ["ESTOP", "FAULT"].includes(st.state) ? `<div class="muted">Stop category ${st.stop_category} (BS EN 60204-1)</div>` : "");
  $("sf-release").hidden = !st.estop_pressed;
  $("sf-reset").disabled = !st.can_reset;
  $("sf-start").disabled = !(st.state === "READY" || st.state === "PAUSED");
  $("sf-stop").disabled = st.state !== "RUNNING";
  document.querySelectorAll("#sf-modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === st.mode));
  const job = st.job ? `'${st.job.name}'` : "the next job";
  $("sf-check-state").innerHTML = st.checklist_ok ? `<span class="good">&#10003; confirmed for ${job}</span>`
    : `<span class="warn">needed for ${job}${st.job && st.job.state === "finished" ? " - the last job finished: clear the table and tray first" : ""}</span>`;
  const inputs = [["gate_closed", "Gate", "closed", "OPEN"], ["curtain_clear", "Light curtain", "clear", "BROKEN"],
    ["extraction_on", "Fume extraction", "on", "OFF"]];
  $("sf-inputs").innerHTML = inputs.map(([k, name, good, bad]) => {
    const v = st.inputs[k], gpio = st.input_source[k] === "gpio";
    const btn = gpio ? '<span class="muted small">real switch (GPIO)</span>'
      : k === "curtain_clear" ? `<button data-hold-input="${k}">Hold to break the beam</button>`
        : `<button data-input="${k}" data-value="${v ? 0 : 1}">${v ? (k === "gate_closed" ? "Open gate" : "Switch off") : (k === "gate_closed" ? "Close gate" : "Switch on")}</button>`;
    return `<tr><td><span class="dot ${v ? "ok" : "bad"}"></span>${name}</td><td><b>${v ? good : bad}</b></td><td>${btn}</td></tr>`;
  }).join("") +
    `<tr><td><span class="dot ${st.estop_pressed ? "bad" : "ok"}"></span>E-stops</td><td><b>${st.estop_pressed ? "PRESSED (" + st.estop_sources.join(", ") + ")" : "released"}</b></td><td></td></tr>` +
    `<tr><td><span class="dot ${st.camera.in_danger ? "bad" : "ok"}"></span>Camera</td><td><b>${st.camera.enabled ? (st.camera.in_danger ? "person in DANGER zone" : st.camera.in_warning ? "person in warning zone" : "zones clear") : "off"}</b></td><td></td></tr>`;
  const d = st.safety_distance;
  $("sf-distance").innerHTML = `<div>Mount the light curtain at least <b>${d.S_mm} mm</b> from the nearest moving part.</div>
    <div class="muted small">${d.formula}: T = machine stopping time + curtain response, C = 8(d - 14) for a ${d.d_mm} mm curtain.
    Measure the real stopping time on the machine and put it in config/cell.toml.</div>`;
  $("sf-log").innerHTML = st.events.map((e) => `<div class="${e.kind}">${e.time.slice(11)} ${e.text}</div>`).join("");
  wireInputs();
}

function wireInputs() {
  document.querySelectorAll("[data-input]").forEach((b) => (b.onclick = () => act("input", { name: b.dataset.input, value: b.dataset.value === "1" })));
  document.querySelectorAll("[data-hold-input]").forEach((b) => {
    b.onpointerdown = () => act("input", { name: b.dataset.holdInput, value: false });
    b.onpointerup = b.onpointerleave = () => act("input", { name: b.dataset.holdInput, value: true });
  });
}

function renderChecklist(items) {
  $("sf-checklist").innerHTML = items.map((t, i) => `<label><input type="checkbox" data-ck="${i}"> ${t}</label>`).join("");
  const boxes = () => [...document.querySelectorAll("[data-ck]")];
  const ok = $("sf-check-ok");
  ok.disabled = true;
  boxes().forEach((b) => (b.onchange = () => (ok.disabled = !boxes().every((x) => x.checked))));
  ok.onclick = async () => { await act("checklist"); boxes().forEach((b) => (b.checked = false)); ok.disabled = true; };
}

// ---------------------------------------------------------------- situation + advisor
async function situation() {
  try {
    const s = await get("/api/situation");
    $("situation").textContent = s.text || "-";
    $("adv-status").textContent = s.advisor ? "AI advisor is on - advisory only, it can't move or reset anything."
      : s.advisor_why + " The plain-English summary on the Machine tab works without it.";
    $("adv-ask").disabled = !s.advisor;
  } catch (e) { /* ignore */ }
}

async function askAdvisor() {
  const q = $("adv-q").value.trim();
  if (!q) return;
  $("adv-answer").innerHTML = '<div class="muted">thinking&hellip;</div>';
  try {
    const r = await post("/api/assistant", { question: q });
    $("adv-answer").innerHTML = r.answer ? `<div>${r.answer.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c]).replace(/\n/g, "<br>")}</div>`
      : `<div class="bad">${r.error}</div>`;
  } catch (e) {
    $("adv-answer").innerHTML = `<div class="bad">${e.message}</div>`;
  }
}

// ---------------------------------------------------------------- set up
export async function initSafety() {
  $("btn-estop").onclick = estop;
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); estop(); } });
  const release = () => act("release", { source: "screen" });
  $("btn-release").onclick = release;
  $("sf-release").onclick = release;
  $("btn-safety-reset").onclick = () => act("reset");
  $("sf-reset").onclick = () => act("reset");
  $("sf-start").onclick = () => act("start");
  $("sf-stop").onclick = () => act("stop");
  document.querySelectorAll("#sf-modes button").forEach((b) => (b.onclick = async () => {
    let lockout = false;
    if (b.dataset.mode === "MAINTENANCE") {
      lockout = confirm("Maintenance: isolate the machine at its main switch and fit YOUR padlock and tag (Lock Out Tag Out).\n\nHave you done this?");
      if (!lockout) return;
    }
    act("mode", { mode: b.dataset.mode, lockout_confirmed: lockout });
  }));
  const hold = $("btn-hold");
  const setHold = (on) => { safety.holding = on; hold.classList.toggle("active", on); if (on) tick(); };
  hold.onpointerdown = () => setHold(true);
  hold.onpointerup = hold.onpointerleave = hold.onpointercancel = () => setHold(false);
  $("adv-ask").onclick = askAdvisor;
  const st = await get("/api/safety");
  renderChecklist(st.checklist);
  accept(st);
  setInterval(tick, 200);
  setInterval(() => { if (!connected() && safety.status) render(safety.status); }, 500);
  setInterval(situation, 1000);
  situation();
}
