// Prototype tab: the 1:10 prototype as a 3D assembly. Every solid is named after its part number
// (the shopping-list line, P01 ...) and its position (the copy, P11-2 ...). Balloons show the
// numbers; click a part or a row to see what it is, where it goes and where to buy it.
import * as THREE from "three";
import { OrbitControls } from "orbit";
import { RoomEnvironment } from "room";
import { get } from "./api.js";

const $ = (id) => document.getElementById(id);
const v = {};                                   // viewer state
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function initPrototype() {
  const tab = document.querySelector('.tabs button[data-tab="proto"]');
  tab.addEventListener("click", () => { if (!v.started) start(); });
}

async function start() {
  v.started = true;
  const [{ GLTFLoader }, info] = await Promise.all([import("gltf"), get("/api/prototype")]);
  v.bom = Object.fromEntries(info.bom.map((r) => [r.part_no, r]));
  v.positions = info.positions;
  v.byTag = Object.fromEntries(info.positions.map((p) => [p.tag, p]));
  const canvas = $("pr-canvas");
  const r = (v.renderer = new THREE.WebGLRenderer({ canvas, antialias: true }));
  r.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  r.outputColorSpace = THREE.SRGBColorSpace;
  r.toneMapping = THREE.ACESFilmicToneMapping;
  v.scene = new THREE.Scene();
  v.scene.background = new THREE.Color(0xe9edf0);
  v.scene.environment = new THREE.PMREMGenerator(r).fromScene(new RoomEnvironment(), 0.04).texture;
  v.scene.add(new THREE.HemisphereLight(0xffffff, 0x777777, 0.7));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(1, -2, 3);
  v.scene.add(sun);
  v.camera = new THREE.PerspectiveCamera(35, 1, 0.01, 50);
  v.camera.up.set(0, 0, 1);
  v.controls = new OrbitControls(v.camera, canvas);
  v.controls.enableDamping = true;
  const gltf = await new GLTFLoader().loadAsync("models/prototype.glb");
  for (const c of gltf.scene.children) c.quaternion.identity();       // the GLB is written Y-up
  v.scene.add(gltf.scene);
  // every solid: its tag (P11-2), the meshes it is made of, its home position (for exploding)
  v.solids = {};
  gltf.scene.traverse((o) => {
    const m = /^(P\d\d-\d+)[ _]/.exec(o.name || "");        // three.js turns the space into _
    if (!m || v.solids[m[1]] || !v.byTag[m[1]]) return;
    const meshes = [];
    const clear = v.byTag[m[1]].item.startsWith("Polycarbonate");          // the door is clear plastic: see through it
    o.traverse((x) => {
      if (!x.isMesh) return;
      x.material = x.material.clone();
      if (clear) Object.assign(x.material, { transparent: true, opacity: 0.18, depthWrite: false, color: new THREE.Color(0xbfd4e6) });
      x.userData.tag = m[1];
      meshes.push(x);
    });
    v.solids[m[1]] = { node: o, meshes, home: o.position.clone(), info: v.byTag[m[1]] };
  });
  const box = new THREE.Box3().setFromObject(gltf.scene);
  v.centre = box.getCenter(new THREE.Vector3());
  v.size = box.getSize(new THREE.Vector3()).length();
  renderList();
  wire();
  view("iso");
  resize();
  window.addEventListener("resize", resize);
  frame();
}

function resize() {
  const c = $("pr-canvas"), w = c.clientWidth, h = c.clientHeight;
  if (!w || !h) return;
  v.renderer.setSize(w, h, false);
  v.camera.aspect = w / h;
  v.camera.updateProjectionMatrix();
}

export function view(name) {
  const c = v.centre, d = v.size * 1.15;
  const dirs = { iso: [0.95, -0.85, 0.6], front: [0, -1, 0.02], side: [1, 0, 0.02], top: [0, -0.22, 1], fit: [0.95, -0.85, 0.6] };
  const dir = new THREE.Vector3(...dirs[name]).normalize();
  v.camera.position.copy(c).addScaledVector(dir, d);
  v.controls.target.copy(c);
  v.controls.update();
}

// ---------------------------------------------------------------- list, selection, info
function inModel(pn) { return v.positions.filter((p) => p.pn === pn); }

function link(row) {
  if (!row.link) return '<i class="muted">make / print it</i>';
  const search = /search|\?s=|\/s\?k=|searchTerm|\?q=/.test(row.link);
  return `<a href="${esc(row.link)}" target="_blank" rel="noopener">${search ? "search shop" : "buy"}</a>`;
}

function renderList() {
  const rows = Object.values(v.bom).map((b) => {
    const n = inModel(b.part_no).length;
    return `<tr data-pn="${b.part_no}"><td class="pn">${b.part_no}</td><td>${esc(b.item)}<div class="muted">${n ? `${n} in the model` : "not drawn (wiring, inside the box, tools)"}</div></td>
      <td>buy ${esc(b.qty)}</td><td>£${(+b.approx_gbp_each).toFixed(+b.approx_gbp_each < 10 && +b.approx_gbp_each % 1 ? 2 : 0)}</td><td>${link(b)}</td></tr>`;
  }).join("");
  $("pr-list").innerHTML = `<tr><th>Part</th><th>What</th><th>Qty</th><th>Each</th><th></th></tr>${rows}`;
  $("pr-list").querySelectorAll("tr[data-pn]").forEach((tr) => (tr.onclick = (e) => { if (e.target.tagName !== "A") select(tr.dataset.pn); }));
}

export function select(pn, tag = null) {
  v.sel = pn;
  v.selTag = tag;
  for (const [t, s] of Object.entries(v.solids)) {
    const on = s.info.pn === pn, me = t === tag;
    for (const m of s.meshes) {
      m.material.emissive = new THREE.Color(on ? (me ? 0xff6a00 : 0xd04a00) : 0x000000);
      m.material.emissiveIntensity = on ? (me ? 0.9 : 0.45) : 0;
    }
  }
  document.querySelectorAll("#pr-list tr").forEach((tr) => tr.classList.toggle("sel", tr.dataset.pn === pn));
  const row = document.querySelector(`#pr-list tr[data-pn="${pn}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
  const b = v.bom[pn], copies = inModel(pn), p = tag ? v.byTag[tag] : copies[0];
  $("pr-info").innerHTML = `<h3>${tag || pn} &mdash; ${esc(b.item)}</h3>
    ${p ? `<div><b>${tag ? "This position" : "Position " + p.tag}:</b> ${esc(p.label)}</div><div>Where: ${esc(p.where)} (x ${p.centre[0]}, y ${p.centre[1]}, z ${p.centre[2]} mm)</div>` : "<div>Not drawn in the model.</div>"}
    <div>${copies.length ? `In the model: ${copies.map((c) => c.tag).join(", ")}` : ""}</div>
    <div>Buy: <b>${esc(b.qty)}</b> &times; about £${b.approx_gbp_each} &middot; ${esc(b["where (UK)"])} &middot; ${link(b)}</div>
    <div class="muted">${esc(b["specification / what to look for"])}</div>`;
}

function wire() {
  const canvas = $("pr-canvas");
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const rect = canvas.getBoundingClientRect();
    const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1), v.camera);
    const hit = ray.intersectObjects(Object.values(v.solids).flatMap((s) => s.meshes), false)[0];
    if (hit) select(v.solids[hit.object.userData.tag].info.pn, hit.object.userData.tag);
  });
  document.querySelectorAll("[data-pview]").forEach((b) => (b.onclick = () => view(b.dataset.pview)));
  $("pr-explode").oninput = (e) => explode(+e.target.value);
  $("pr-balloons").onchange = () => { v.balloonMode = $("pr-balloons").value; };
  v.balloonMode = "part";
}

// pull every part away from the middle so you can see what goes where
export function explode(k) {
  for (const s of Object.values(v.solids)) {
    const c = new THREE.Vector3(...s.info.centre).multiplyScalar(0.001);
    const away = c.sub(v.centre).multiplyScalar(k * 0.9);
    s.node.position.copy(s.home).add(away);
  }
}

// ---------------------------------------------------------------- balloons with leader lines
function balloons() {
  const layer = $("pr-balloons-layer"), svg = $("pr-leaders"), canvas = $("pr-canvas");
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const mode = v.balloonMode;
  const shown = mode === "off" ? [] : mode === "all" ? Object.keys(v.solids)
    : [...new Set(Object.values(v.solids).map((s) => s.info.pn))].map((pn) => Object.keys(v.solids).find((t) => v.solids[t].info.pn === pn));
  if (!v.balloonEls) v.balloonEls = {};
  const lines = [];
  const used = new Set(shown);
  for (const [tag, el] of Object.entries(v.balloonEls)) if (!used.has(tag)) { el.remove(); delete v.balloonEls[tag]; }
  const mid = new THREE.Vector2(w / 2, h / 2);
  const placed = [];
  for (const tag of shown) {
    const s = v.solids[tag];
    const world = new THREE.Vector3(...s.info.centre).multiplyScalar(0.001).add(s.node.position).sub(s.home);
    const p = world.project(v.camera);
    if (p.z > 1) continue;
    const x = (p.x + 1) / 2 * w, y = (1 - p.y) / 2 * h;
    const out = new THREE.Vector2(x, y).sub(mid);
    if (out.length() < 1) out.set(1, -1);
    out.normalize();
    // move out from the part; if another balloon is already there, keep going (no overlaps)
    let dist = mode === "all" ? 26 : 46, bx, by;
    const gap = mode === "all" ? 46 : 30;
    for (let tries = 0; tries < 30; tries++, dist += 14) {
      bx = Math.min(Math.max(x + out.x * dist, 16), w - 16);
      by = Math.min(Math.max(y + out.y * dist, 16), h - 16);
      if (placed.every(([px, py]) => Math.abs(px - bx) > gap || Math.abs(py - by) > 24)) break;
    }
    placed.push([bx, by]);
    let el = v.balloonEls[tag];
    if (!el) {
      el = v.balloonEls[tag] = document.createElement("div");
      el.className = "pr-balloon";
      el.onclick = () => select(s.info.pn, tag);
      layer.appendChild(el);
    }
    el.textContent = mode === "all" ? tag : s.info.pn;
    el.title = `${tag} - ${s.info.item}`;
    el.style.left = `${bx}px`;
    el.style.top = `${by}px`;
    el.classList.toggle("sel", s.info.pn === v.sel);
    lines.push(`<line x1="${x}" y1="${y}" x2="${bx}" y2="${by}" stroke="#1f2933" stroke-width="1"/><circle cx="${x}" cy="${y}" r="2.2" fill="#1f2933"/>`);
  }
  svg.innerHTML = lines.join("");
}

function frame() {
  requestAnimationFrame(frame);
  if (!document.getElementById("tab-proto").classList.contains("on")) return;
  v.controls.update();
  v.renderer.render(v.scene, v.camera);
  balloons();
}

window.prototypeView = v;                       // handy in the browser console (and for the assembly drawing)
