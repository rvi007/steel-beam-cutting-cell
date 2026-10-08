// The 3D cell: building, machine, steel, effects. Machine coordinates (metres):
// X along the 12 m work area, Y across, Z up.
import * as THREE from "three";
import { OrbitControls } from "orbit";
import { RoomEnvironment } from "room";
import { Cables } from "./cables.js";
import { handFrames } from "./kinematics.js";

const C = { floor: 0xb9bcb8 };

export class CellScene {
  constructor(canvas, machine) {
    this.m = machine;
    this.suffix = machine.work_length === 12 ? "" : `_${machine.work_length}m`;    // which machine size's model
    this.canvas = canvas;
    this.quality = localStorage.getItem("quality") || "high";
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: this.quality === "high", powerPreference: "high-performance" });
    this.renderer.setPixelRatio(this.quality === "high" ? Math.min(window.devicePixelRatio, 1.5) : 1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = this.quality === "high";
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xdfe4e8);
    // soft reflections so steel and paint look like the real thing
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.fog = new THREE.Fog(0xdfe4e8, 30, 70);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.05, 200);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.origin = new THREE.Vector3(0, machine.beam_y, machine.bed_z);
    this.follow = null;

    this._lights();
    this._building();
    this._cell();
    this.hands = {};
    for (const key of ["cutter", "handler"]) this.hands[key] = { cfg: machine.hands[key], tip: new THREE.Vector3(), dir: new THREE.Vector3() };
    this._effects();
    this.steel = new THREE.Group();
    this.scene.add(this.steel);
    this.view("overview");
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  setQuality(q) {
    localStorage.setItem("quality", q);
    location.reload();
  }

  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  // ---------------------------------------------------------------- views
  view(name) {
    const L = this.m.work_length;
    const spots = {
      overview: [[L / 2 - 6.5, -11.5, 8.5], [L / 2, 0, 1.2]],
      side: [[L / 2, -14, 2.2], [L / 2, 0, 1.6]],
      top: [[L / 2, -0.01, 19], [L / 2, 0, 0]],
      end: [[L + 5.5, -1.5, 3.2], [L / 2 + 2, -0.4, 1.3]],
    };
    this.follow = name === "cutter" || name === "handler" ? name : null;
    if (spots[name]) {
      this.camera.position.set(...spots[name][0]);
      this.controls.target.set(...spots[name][1]);
    } else if (this.follow) {
      const tip = this.hands[this.follow].tip;
      this.controls.target.copy(tip);
      const back = name === "handler" ? new THREE.Vector3(-2.4, -3.6, 0.9) : new THREE.Vector3(-1.6, -2.6, 1.1);
      this.camera.position.copy(tip).add(back);
    }
    this.controls.update();
  }

  // ---------------------------------------------------------------- lights & building
  _lights() {
    this.scene.add(new THREE.HemisphereLight(0xf4f7fb, 0x6a6258, 0.6));
    // high roof light (like a factory's roof lights) so the runways' shadows miss the bed
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(4, -2.5, 22);
    sun.target.position.set(6, 0, 0);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -11, right: 11, top: 7, bottom: -7, near: 1, far: 40 });
    sun.shadow.bias = -0.0004;
    this.scene.add(sun, sun.target);
    const fill = new THREE.DirectionalLight(0xcfe0ff, 0.5);
    fill.position.set(14, 10, 6);
    const front = new THREE.DirectionalLight(0xfff4e6, 0.9);      // the operator's side, lights the web face
    front.position.set(6, -12, 3);
    this.scene.add(fill, front);
  }

  _box(w, d, h, color, x, y, z, opts = {}) {
    const mat = opts.material || new THREE.MeshStandardMaterial({ color, metalness: opts.metal ?? 0.3, roughness: opts.rough ?? 0.6, transparent: !!opts.opacity, opacity: opts.opacity ?? 1 });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, d, h), mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = !opts.noShadow;
    mesh.receiveShadow = true;
    (opts.parent || this.scene).add(mesh);
    return mesh;
  }

  _building() {
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 34), new THREE.MeshStandardMaterial({ color: C.floor, roughness: 0.95 }));
    floor.position.set(6, 0, 0);
    floor.receiveShadow = true;
    this.scene.add(floor);
    const grid = new THREE.GridHelper(40, 40, 0x8e928f, 0xa9ada9);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(6, 0, 0.002);
    grid.material.transparent = true;
    grid.material.opacity = 0.35;
    this.scene.add(grid);
    // painted walkway lines around the cell
    for (const y of [-2.45, 2.45]) this._box(17.5, 0.08, 0.004, 0xf2c230, 6, y, 0.003, { noShadow: true });
  }

  // ---------------------------------------------------------------- the machine, from the CAD model
  // web/models/*.glb are made by `python3 -m beamcell.cad cell` from the same solids as
  // cad/beam_cell.step, so what you see here is the CAD model. Moving bodies (bridges, carriages,
  // masts, arm links, the gate) are modelled in their own frames and posed here by the kinematics.
  async load() {
    const { GLTFLoader } = await import("gltf");
    const loader = new GLTFLoader();
    const [cell, moving, info] = await Promise.all([
      loader.loadAsync(`models/cell${this.suffix}.glb`), loader.loadAsync("models/moving.glb"),
      fetch(`models/labels${this.suffix}.json`).then((r) => r.json())]);
    this.labels = info.labels;
    const prep = (root) => {
      for (const c of root.children) c.quaternion.identity();   // the GLB's root node turns Z-up into Y-up: undo it
      root.traverse((o) => {
        if (!o.isMesh) return;
        o.castShadow = o.receiveShadow = true;
        const m = o.material;
        m.metalness = Math.min(m.metalness ?? 0.3, 0.45);
        m.roughness = Math.max(m.roughness ?? 0.6, 0.45);
        const n = this._name(o);
        if (/^(fence_mesh|gate_mesh)/.test(n)) { o.material = m.clone(); Object.assign(o.material, { transparent: true, opacity: 0.2, depthWrite: false }); o.castShadow = false; }
      });
    };
    prep(cell.scene);
    this.scene.add(cell.scene);
    this.cell = cell.scene;
    // stack light lamps: their own materials, so the safety state can light them
    this.lamps = {};
    for (const name of ["red", "amber", "green", "blue"]) {
      const node = cell.scene.getObjectByName("lamp_" + name);
      node?.traverse((o) => {
        if (!o.isMesh) return;
        o.material = o.material.clone();
        o.material.emissive = o.material.color.clone();
        o.material.emissiveIntensity = 0.05;
        this.lamps[name] = o.material;
      });
    }
    // moving bodies: each becomes a group whose matrix the kinematics set every frame
    prep(moving.scene);
    const body = (name) => {
      const node = moving.scene.getObjectByName(name);
      const g = new THREE.Group();
      g.matrixAutoUpdate = false;
      if (node) { node.position.set(0, 0, 0); node.quaternion.identity(); g.add(node); }
      this.scene.add(g);
      return g;
    };
    for (const key of ["cutter", "handler"]) {
      const H = this.hands[key];
      H.bridge = body(`${key}_bridge`);
      H.carriage = body(`${key}_carriage`);
      H.mast = body(`${key}_mast`);
      H.links = [0, 1, 2, 3, 4, 5, 6].map((k) => body(`${key}_link${k}`));
    }
    const [hx, hy] = info.gate_hinge_m;
    const gate = moving.scene.getObjectByName("gate");
    this.gate = new THREE.Group();
    this.gate.position.set(hx, hy, 0);
    if (gate) { gate.position.set(0, 0, 0); gate.quaternion.identity(); this.gate.add(gate); }
    this.scene.add(this.gate);
    this.cables = new Cables(this.scene, this.m);       // energy chains and dress packs follow the hands
    this.loaded = true;
    for (const key of ["cutter", "handler"]) if (this.hands[key].last) this.pose(key, ...this.hands[key].last);
  }

  // the CAD name of a mesh: the nearest node (itself or a parent) that has a label
  _name(o) {
    for (let n = o; n; n = n.parent) if (n.name && this.labels && this.labels[n.name]) return n.name;
    for (let n = o; n; n = n.parent) if (n.name) return n.name;
    return "";
  }

  // what is under the mouse: the CAD label of that solid, or null
  labelAt(ndc) {
    if (!this.loaded) return null;
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const targets = [this.cell, this.gate, ...Object.values(this.hands).flatMap((H) => [H.bridge, H.carriage, H.mast, ...H.links])];
    const hit = ray.intersectObjects([this.steel, ...targets], true).find((h) => h.object.isMesh && h.object.visible && !h.object.material.transparent);
    if (!hit) return null;
    if (this.steel.getObjectById(hit.object.id)) return "Steel on the machine";
    return this.labels[this._name(hit.object)] || null;
  }

  _cell() {
    // light curtain beams across the infeed opening (drawn here: they light up when broken)
    const m = this.m, [xa, xb] = m.x_limits, W = m.width;
    const fx0 = xa - 0.6, fy = W / 2 + 0.6;
    const cy0 = -fy, cy1 = -fy + (2 * fy) / Math.round((2 * fy) / 2);
    this.beams = new THREE.Group();
    for (let z = 0.25; z <= 1.65; z += 0.07) {
      const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(fx0 - 0.12, cy0 + 0.05, z), new THREE.Vector3(fx0 - 0.12, cy1 - 0.05, z)]);
      this.beams.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xff3020, transparent: true, opacity: 0.18 })));
    }
    this.scene.add(this.beams);
    this.trayZ = m.scrap_tray_z;
    this.lamps = {};
  }

  // Show the safety state in the 3D cell: stack light, gate, light curtain.
  setSafety(st) {
    const blink = Math.floor(performance.now() / 500) % 2 === 0;
    for (const [name, mat] of Object.entries(this.lamps)) {
      const on = !!st.lamps[name] && (name !== "blue" || blink);
      mat.emissiveIntensity = on ? 2.2 : 0.05;
    }
    const open = !st.inputs.gate_closed;
    if (this.gate) this.gate.rotation.z += ((open ? -1.4 : 0) - this.gate.rotation.z) * 0.5;
    const broken = !st.inputs.curtain_clear;
    this.beams.children.forEach((l) => { l.material.opacity = broken ? 0.95 : 0.18; });
  }

  // Put a hand at gantry g and joints q.
  pose(key, g, q) {
    const H = this.hands[key], rz = this.m.rail_z;
    H.last = [g, q];
    const F = handFrames(H.cfg, g, q);
    H.tip.setFromMatrixPosition(F[7]);
    H.dir.setFromMatrixColumn(F[7], 2);
    if (!this.loaded) return;
    H.bridge.matrix.makeTranslation(g[0], 0, rz);
    H.carriage.matrix.makeTranslation(g[0], g[1], rz - 0.12);
    H.mast.matrix.makeTranslation(g[0], g[1], g[2]);
    for (let k = 0; k < 7; k++) H.links[k].matrix.copy(F[k]);
    for (const b of [H.bridge, H.carriage, H.mast, ...H.links]) b.matrixWorldNeedsUpdate = true;
    this.cables.update(key, H.cfg, g, q);
  }

  // ---------------------------------------------------------------- effects
  _effects() {
    this.arc = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.0015, 0.03, 8),
      new THREE.MeshBasicMaterial({ color: 0xc8e6ff }));
    this.arc.visible = false;
    this.scene.add(this.arc);
    this.glow = new THREE.PointLight(0xffa040, 0, 1.6, 1.5);
    this.scene.add(this.glow);
    // the profile laser while the Cutter measures the bar: a red fan of light from the torch down across the bar
    const fan = new THREE.PlaneGeometry(0.42, 0.25);
    fan.rotateY(Math.PI / 2);                       // spans across the bar (Y) and down (Z)
    fan.translate(0, 0, -0.125);
    this.laser = new THREE.Mesh(fan, new THREE.MeshBasicMaterial({ color: 0xff2a2a, transparent: true, opacity: 0.35,
      side: THREE.DoubleSide, depthWrite: false }));
    this.laser.visible = false;
    this.scene.add(this.laser);
    const n = 260;
    this.sparkPos = new Float32Array(n * 3);
    this.sparkVel = new Float32Array(n * 3);
    this.sparkAge = new Float32Array(n).fill(9);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(this.sparkPos, 3));
    this.sparks = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xffc04d, size: 0.012, transparent: true,
      opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false }));
    this.sparks.frustumCulled = false;
    this.scene.add(this.sparks);
    this._spark = 0;
  }

  // Plasma arc, glow and sparks at the Cutter's tip. `emit`: throw new sparks (machine running).
  scanLaser(on) {
    this.laser.visible = on;
    if (on) {
      const H = this.hands.cutter;
      this.laser.position.copy(H.tip);
      this.laser.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, -1), H.dir);   // down on the flange, sideways on the web
    }
  }

  torch(on, dt, emit) {
    const H = this.hands.cutter;
    this.arc.visible = on;
    this.glow.intensity = on ? 1.4 + Math.random() * 0.8 : 0;
    if (on) {
      const up = new THREE.Vector3(0, 1, 0);
      this.glow.intensity = emit ? this.glow.intensity : 1.2;
      this.arc.position.copy(H.tip).addScaledVector(H.dir, 0.012);
      this.arc.quaternion.setFromUnitVectors(up, H.dir);
      this.glow.position.copy(H.tip).addScaledVector(H.dir, -0.05);
      for (let k = 0; emit && k < 9; k++) {                 // emit
        const i = this._spark = (this._spark + 1) % this.sparkAge.length;
        this.sparkAge[i] = 0;
        this.sparkPos.set([H.tip.x, H.tip.y, H.tip.z], i * 3);
        const v = new THREE.Vector3((Math.random() - 0.5) * 1.6, (Math.random() - 0.5) * 1.6, -Math.random() * 1.2)
          .addScaledVector(H.dir, 1.4);
        this.sparkVel.set([v.x, v.y, v.z], i * 3);
      }
    }
    for (let i = 0; i < this.sparkAge.length; i++) {
      if (this.sparkAge[i] > 0.7) { this.sparkPos[i * 3 + 2] = -10; continue; }
      this.sparkAge[i] += dt;
      this.sparkVel[i * 3 + 2] -= 9.81 * dt;
      for (let k = 0; k < 3; k++) this.sparkPos[i * 3 + k] += this.sparkVel[i * 3 + k] * dt;
      if (this.sparkPos[i * 3 + 2] < 0.01) { this.sparkPos[i * 3 + 2] = 0.01; this.sparkVel[i * 3 + 2] *= -0.3; }
    }
    this.sparks.geometry.attributes.position.needsUpdate = true;
  }

  render() {
    if (this.follow) {
      const tip = this.hands[this.follow].tip;
      const delta = new THREE.Vector3().subVectors(tip, this.controls.target);
      this.controls.target.add(delta);
      this.camera.position.add(delta);
    }
    this.controls.update();
    const t0 = performance.now();
    this.renderer.render(this.scene, this.camera);
    this._adapt(performance.now() - t0);
  }

  // Slow computer (or no GPU)? Draw fewer pixels, then drop shadows, so the page stays responsive -
  // the safety heartbeat comes from this page, and a frozen page stops the machine.
  _adapt(ms) {
    this.frameMs = this.frameMs === undefined ? ms : this.frameMs * 0.9 + ms * 0.1;
    if (this.frameMs < 120 || performance.now() - (this.adapted || 0) < 2000) return;
    this.adapted = performance.now();
    if (this.renderer.shadowMap.enabled) {
      this.renderer.shadowMap.enabled = false;
      this.scene.traverse((o) => { if (o.material) o.material.needsUpdate = true; });
    } else if (this.renderer.getPixelRatio() > 0.45) {
      this.renderer.setPixelRatio(this.renderer.getPixelRatio() * 0.7);
      this.resize();
    } else return;
    console.info(`3D view: frames took ${Math.round(this.frameMs)} ms - lowered the quality to keep the page responsive`);
    this.frameMs = 60;
  }
}
