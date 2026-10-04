// Camera tab: live picture with the people the detector finds and the two zones (warning:
// slow down, danger: protective stop). The safety controller on the server reads the zones.
import { get, post } from "./api.js";
import { app } from "./app.js";

const $ = (id) => document.getElementById(id);

function show(st) {
  $("cam-status").innerHTML = `<div>Status: <b>${st.message}</b></div><div>Detector: ${st.detector}</div>
    <div>People seen: ${st.people} ${st.in_danger ? '<b class="bad">- in the DANGER zone</b>' : st.in_warning ? '<b class="warn">- in the warning zone</b>' : ""}</div>
    <div>${st.fps} pictures/s</div>`;
  const pill = $("pill-camera");
  pill.textContent = st.enabled ? (st.in_danger ? "Person: danger zone" : st.in_warning ? "Person: warning zone" : "Camera on") : "Camera off";
  pill.className = "pill " + (st.enabled ? (st.in_danger ? "bad" : st.in_warning ? "run" : "ok") : "dim");
  $("cam-empty").hidden = st.enabled && st.has_frame;
  document.querySelectorAll("[data-zone]").forEach((el) => {
    if (document.activeElement !== el) el.value = st.zones[el.dataset.zone][+el.dataset.i];
  });
}

async function poll() {
  try { show(await get("/api/camera")); } catch (e) { /* server busy */ }
}

export async function initCamera() {
  const info = app.info.system;
  const sel = $("cam-model");
  for (const m of info.yolo_models || []) sel.add(new Option("YOLO - " + m, m));
  sel.add(new Option("HOG people detector (built in)", "hog"));
  if (!info.opencv) $("cam-status").innerHTML = '<div class="bad">OpenCV isn\'t installed on the server - the camera can\'t run.</div>';
  $("cam-source").onchange = () => ($("cam-file").hidden = $("cam-source").value !== "file");
  $("btn-cam-on").onclick = async () => {
    const src = $("cam-source").value === "file" ? $("cam-file").value : $("cam-source").value;
    const st = await post("/api/camera", { enabled: true, source: src, model: sel.value === "hog" ? "none" : sel.value });
    show(st);
    $("cam-img").src = "/camera.mjpg?" + Date.now();
  };
  $("btn-cam-off").onclick = async () => { show(await post("/api/camera", { enabled: false })); $("cam-img").removeAttribute("src"); };
  document.querySelectorAll("[data-zone]").forEach((el) => (el.onchange = () => {
    const zone = el.dataset.zone;
    const values = [...document.querySelectorAll(`[data-zone=${zone}]`)].map((x) => +x.value);
    post("/api/camera", { zones: { [zone]: values } }).then(show);
  }));
  await poll();
  setInterval(poll, 600);
}
