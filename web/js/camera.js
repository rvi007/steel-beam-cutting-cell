// Camera tab: live picture with the people the detector finds, the safety zone, and the link
// to the machine (a person in the zone stops it, like a light curtain).
import { get, post } from "./api.js";
import { app, setSafetyStop, toast } from "./app.js";

const $ = (id) => document.getElementById(id);
let status = null;

function show(st) {
  status = st;
  $("cam-status").innerHTML = `<div>Status: <b>${st.message}</b></div><div>Detector: ${st.detector}</div>
    <div>People seen: ${st.people} ${st.in_zone ? '<b class="bad">- in the zone</b>' : ""}</div><div>${st.fps} pictures/s</div>`;
  const pill = $("pill-camera");
  pill.textContent = st.enabled ? (st.in_zone ? "Person in zone" : "Camera on") : "Camera off";
  pill.className = "pill " + (st.enabled ? (st.in_zone ? "bad" : "ok") : "dim");
  $("cam-empty").hidden = st.enabled && st.has_frame;
  ["z0", "z1", "z2", "z3"].forEach((id, i) => { if (document.activeElement !== $(id)) $(id).value = st.zone[i]; });
  if ($("cam-link").checked && st.enabled && st.safety_stop && !app.safetyStop) setSafetyStop(true, "Camera saw someone in the zone.");
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
  ["z0", "z1", "z2", "z3"].forEach((id) => ($(id).onchange = () =>
    post("/api/camera", { zone: ["z0", "z1", "z2", "z3"].map((z) => +$(z).value) }).then(show)));
  $("btn-safety-reset").onclick = async () => {
    if (status && status.enabled) {
      const st = await post("/api/camera", { reset: true });
      show(st);
      if (st.safety_stop) return toast("Can't reset: " + st.message, true);
    }
    setSafetyStop(false);
  };
  await poll();
  setInterval(poll, 600);
}
