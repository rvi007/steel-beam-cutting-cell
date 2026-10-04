// Section library: every UK section with its real shape in 3D, and STL export at any scale
// (to 3D print sections or the whole machine for a scale model).
import * as THREE from "three";
import { OrbitControls } from "orbit";
import { STLExporter } from "stl";
import { RoomEnvironment } from "room";
import { get, download } from "./api.js";
import { app, toast } from "./app.js";
import { MAT, stockMesh } from "./geometry.js";

const $ = (id) => document.getElementById(id);
let fam = "UB", current = null, view = null;

const COLS = {
  I: [["h", "h"], ["b", "b"], ["tw", "tw"], ["tf", "tf"], ["r", "r"], ["m", "kg/m"], ["N", "N"], ["n", "n"]],
  U: [["h", "h"], ["b", "b"], ["tw", "tw"], ["tf", "tf"], ["r", "r"], ["m", "kg/m"]],
  L: [["h", "h"], ["b", "b"], ["t", "t"], ["r1", "r1"], ["r2", "r2"], ["m", "kg/m"]],
  M: [["h", "h"], ["b", "b"], ["t", "t"], ["ro", "r out"], ["m", "kg/m"]],
  RO: [["d", "d"], ["t", "t"], ["m", "kg/m"]],
};

function rows() {
  const q = $("lib-search").value.trim().toLowerCase();
  if (!q) return app.sections[fam];
  return Object.values(app.sections).flat().filter((s) => s.title.toLowerCase().includes(q));
}

function renderFamilies() {
  const box = $("lib-families");
  box.innerHTML = "";
  for (const [f, name] of Object.entries(app.info.families)) {
    const b = document.createElement("button");
    b.innerHTML = `<span>${f}</span><span class="muted small">${app.sections[f].length}</span>`;
    b.title = name;
    if (f === fam) b.classList.add("on");
    b.onclick = () => { fam = f; $("lib-search").value = ""; renderFamilies(); renderList(); };
    box.appendChild(b);
  }
}

function renderList() {
  const list = rows();
  const kind = list[0]?.kind || "I";
  const cols = COLS[kind];
  const t = $("lib-list");
  t.innerHTML = `<thead><tr><th>Section</th>${cols.map(([, n]) => `<th>${n}</th>`).join("")}<th>cut?</th></tr></thead><tbody>` +
    list.map((s, i) => `<tr data-i="${i}" class="${current && s.title === current.title ? "sel" : ""}"><td><b>${s.title}</b>${s.add ? ' <span class="muted small">*</span>' : ""}</td>` +
      cols.map(([k]) => `<td>${s[k] ?? ""}</td>`).join("") + `<td>${s.cuttable ? "&#10003;" : '<span class="muted">-</span>'}</td></tr>`).join("") + "</tbody>";
  t.querySelectorAll("tbody tr").forEach((tr) => (tr.onclick = () => show(list[+tr.dataset.i].title)));
  if (!current && list[0]) show(list[0].title);
}

async function show(title) {
  current = await get("/api/section?title=" + encodeURIComponent(title));
  renderList();
  const s = current;
  const fams = app.info.families;
  $("lib-info").innerHTML = `<h2>${s.title}</h2><div class="muted">${fams[s.family] || s.family}${s.add ? " (additional size, not in BS 4-1)" : ""}</div>
    <table>${Object.entries({ "Depth h": s.h, "Width b": s.b, "Web tw": s.kind === "I" || s.kind === "U" ? s.tw : null, "Flange tf": s.kind === "I" || s.kind === "U" ? s.tf : null,
      "Thickness t": s.t, "Root radius r": s.r ?? s.r1, "Toe radius": s.r2, "Mass": s.m ? s.m + " kg/m" : null,
      "Notch to clear it (N x n)": s.N ? `${s.N} x ${s.n} mm` : null }).filter(([, v]) => v != null).map(([k, v]) => `<tr><td>${k}</td><td><b>${v}</b></td></tr>`).join("")}</table>
    <div class="muted small">${s.cuttable ? "This cell can cut it." : "Shown and exported only - hollow sections need a rotating chuck."}</div>`;
  updateSize();
  build3d();
}

function updateSize() {
  if (!current) return;
  const k = +$("stl-scale").value, L = +$("stl-length").value;
  $("stl-size").textContent = `Printed size: ${(current.b / k).toFixed(1)} x ${(current.h / k).toFixed(1)} x ${(L / k).toFixed(0)} mm` +
    (current.t || current.tw ? ` - thinnest wall ${((current.t || Math.min(current.tw, current.tf)) / k).toFixed(2)} mm` +
      (((current.t || Math.min(current.tw, current.tf)) / k) < 0.8 ? " (too thin to print well - use a bigger scale)" : "") : "");
}

function build3d() {
  const canvas = $("lib-canvas");
  if (!view) {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xdfe4e8);
    scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x777777, 0.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(2, -3, 4);
    scene.add(sun);
    const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 50);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, canvas);
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.2;
    view = { renderer, scene, camera, controls, mesh: null };
    const loop = () => {
      if (document.getElementById("tab-library").classList.contains("on")) {
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (w && h && (canvas.width !== w || canvas.height !== h)) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
        controls.update();
        renderer.render(scene, camera);
      }
      requestAnimationFrame(loop);
    };
    loop();
  }
  if (view.mesh) { view.scene.remove(view.mesh); view.mesh.geometry.dispose(); }
  const s = current, len = Math.max(s.h, s.b) * 2.5;
  view.mesh = stockMesh(s, 0, len, MAT.library, { x: -len / 2000, y: 0, z: -s.h / 2000 });
  view.scene.add(view.mesh);
  const r = Math.max(s.h, s.b, len) / 1000;
  view.camera.position.set(r * 1.3, -r * 1.6, r * 0.9);
  view.controls.target.set(0, 0, 0);
}

function exportSection() {
  if (!current) return;
  const k = +$("stl-scale").value, L = +$("stl-length").value;
  const mesh = stockMesh(current, 0, L, MAT.library, { x: 0, y: 0, z: 0 });
  mesh.scale.setScalar(1000 / k);                       // STL in millimetres at the chosen scale
  mesh.updateMatrixWorld(true);
  const stl = new STLExporter().parse(mesh, { binary: true });
  download(`${current.title.replace(/\s+/g, "_")}_L${L}_1-${k}.stl`, new Blob([stl], { type: "model/stl" }));
}

function exportCell() {
  // the fixed structure + both hands as they stand now, in mm at the chosen scale
  const k = +$("stl-scale").value;
  const group = new THREE.Group();
  app.scene.scene.traverse((o) => {
    if (o.isMesh && o.geometry && !o.isPoints && o.material && !o.material.transparent && o.visible) {
      const m = new THREE.Mesh(o.geometry, o.material);
      o.updateMatrixWorld(true);
      m.matrix.copy(o.matrixWorld);
      m.matrixAutoUpdate = false;
      group.add(m);
    }
  });
  group.scale.setScalar(1000 / k);
  group.updateMatrixWorld(true);
  const stl = new STLExporter().parse(group, { binary: true });
  download(`beam_cell_1-${k}.stl`, new Blob([stl], { type: "model/stl" }));
  toast(`Machine exported at 1:${k} - see docs/SCALE_MODEL.md for how to build it`);
}

const CAD_NAMES = {
  "beam_cell.step": "The whole 12 m cell, full size (every solid named)",
  "prototype_1to5.step": "The 1:5 desktop prototype - bought parts and printed parts (docs/PROTOTYPE.md)",
  "prototype_cut_list.csv": "Prototype: aluminium extrusion cut list",
  "prototype_parts.csv": "Prototype: every part and what to buy or print",
};

async function renderCad() {
  const box = $("cad-files");
  try {
    const r = await get("/api/cad");
    const row = (f) => `<li><a href="/cad/${f.path}" download>${f.path}</a> <span class="muted">${f.kb} kB${CAD_NAMES[f.path] ? " - " + CAD_NAMES[f.path] : ""}</span></li>`;
    const main = r.files.filter((f) => !f.path.startsWith("parts/")), parts = r.files.filter((f) => f.path.startsWith("parts/"));
    box.innerHTML = `<ul>${main.map(row).join("")}</ul>
      <div>Example parts as solids (holes, notches, end cuts): ${parts.map((f) => `<a href="/cad/${f.path}" download>${f.path.slice(6, -5)}</a>`).join(", ")}</div>
      <div>${r.can_make_parts ? "Any part: <b>Export STEP</b> on the Parts tab." : "Any part: export its NC1, then on a PC run <code>python3 -m beamcell.cad parts part.nc1</code>."}</div>`;
  } catch (e) { box.textContent = "CAD files not found: " + e.message; }
}

export function initLibrary() {
  renderCad();
  renderFamilies();
  renderList();
  $("lib-search").oninput = renderList;
  $("stl-scale").onchange = updateSize;
  $("stl-length").oninput = updateSize;
  $("btn-stl").onclick = exportSection;
  $("btn-stl-cell").onclick = exportCell;
}
