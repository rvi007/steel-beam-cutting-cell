// The 3D cell: building, machine, steel, effects. Machine coordinates (metres):
// X along the 12 m work area, Y across, Z up.
import * as THREE from "three";
import { OrbitControls } from "orbit";
import { RoomEnvironment } from "room";
import { handFrames } from "./kinematics.js";
import { MAT, stockMesh } from "./geometry.js";

const C = {
  structure: 0x7d8a96, rail: 0x2b2f33, bridge: 0xf2b632, bridgeDark: 0x23272b, carriage: 0x3a4148,
  housing: 0x2e3338, floor: 0xb9bcb8, fence: 0xf2c230, rack: 0x2f7d4f, bed: 0x6b4a2b, roller: 0x9aa3ab,
};

export class CellScene {
  constructor(canvas, machine) {
    this.m = machine;
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
    for (const key of ["cutter", "handler"]) this.hands[key] = this._hand(machine.hands[key]);
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

  _cyl(r, len, color, opts = {}) {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(opts.r2 ?? r, r, len, opts.seg || 20),
      opts.material || new THREE.MeshStandardMaterial({ color, metalness: opts.metal ?? 0.4, roughness: opts.rough ?? 0.5 }));
    mesh.castShadow = true;
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

  // ---------------------------------------------------------------- the fixed cell
  _cell() {
    const m = this.m, [xa, xb] = m.x_limits, L = xb - xa + 0.6, W = m.width;
    const runway = { outline: ubOutline(457.0, 190.0, 9.0, 14.5, 10.2), holes: [] };
    for (const y of [-W / 2, W / 2]) {
      // runway beam (a UB on its side) with a crane rail on top
      const beam = stockMesh(runway, 0, L * 1000, new THREE.MeshStandardMaterial({ color: C.structure, metalness: 0.45, roughness: 0.55 }),
        { x: xa - 0.3, y, z: m.rail_z - 0.55 });
      this.scene.add(beam);
      this._box(L, 0.06, 0.05, C.rail, (xa + xb) / 2, y, m.rail_z - 0.07, { metal: 0.8, rough: 0.3 });
      // UC columns every ~3.5 m
      const col = { outline: ubOutline(254.1, 254.6, 8.6, 14.2, 12.7), holes: [] };
      for (let i = 0; i <= 4; i++) {
        const x = xa + (i * (xb - xa)) / 4;
        const c = stockMesh(col, 0, (m.rail_z - 0.55) * 1000, new THREE.MeshStandardMaterial({ color: C.structure, metalness: 0.45, roughness: 0.55 }), { x: 0, y: 0, z: 0 });
        c.rotation.set(0, -Math.PI / 2, 0);
        c.position.set(x, y, 0);
        this.scene.add(c);
        this._box(0.5, 0.5, 0.025, 0x777777, x, y, 0.012);          // base plate
      }
    }
    // roller bed for the stock bar
    const by = m.beam_y, bz = m.bed_z;
    for (const dy of [-0.38, 0.38]) this._box(13, 0.1, 0.16, C.bed, 6, by + dy, bz - 0.17);
    for (let x = 0; x <= 12.01; x += 1.0) {
      const roller = this._cyl(0.05, 0.7, C.roller, { metal: 0.8, rough: 0.25 });
      roller.rotation.z = Math.PI / 2;
      roller.rotation.x = 0;
      roller.position.set(x, by, bz - 0.05);
      roller.rotation.set(0, 0, 0);
      roller.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 1, 0));
      if (x % 2 === 0) for (const dy of [-0.38, 0.38]) this._box(0.12, 0.12, bz - 0.25, C.bed, x, by + dy, (bz - 0.25) / 2);
    }
    // outfeed rack (cantilever arms)
    for (let x = 0.5; x <= 12; x += 1.5) {
      this._box(0.12, 0.12, bz, C.rack, x, m.outfeed_y + 0.42, bz / 2);
      this._box(0.1, 0.95, 0.08, C.rack, x, m.outfeed_y, bz - 0.04);
    }
    // scrap skip under the bed
    this.skip = { x: 0.4, y: by, z: 0.32 };
    const skip = new THREE.Group();
    const skipMat = new THREE.MeshStandardMaterial({ color: 0x2e5e8c, metalness: 0.3, roughness: 0.6 });
    this._box(1.2, 0.9, 0.04, 0, 0, 0, 0.02, { parent: skip, material: skipMat });
    for (const [w, d, x, y] of [[1.2, 0.04, 0, -0.45], [1.2, 0.04, 0, 0.45], [0.04, 0.9, -0.6, 0], [0.04, 0.9, 0.6, 0]])
      this._box(w, d, 0.4, 0, x, y, 0.2, { parent: skip, material: skipMat });
    skip.position.set(this.skip.x, by, 0);
    this.scene.add(skip);
    // safety fence with a gate at the front, light-curtain posts at the gate
    const fenceMat = new THREE.MeshStandardMaterial({ color: C.fence, metalness: 0.2, roughness: 0.6 });
    const meshMat = new THREE.MeshStandardMaterial({ color: 0x222222, transparent: true, opacity: 0.18, side: THREE.DoubleSide });
    const fx0 = xa - 0.6, fx1 = xb + 0.6, fy = W / 2 + 0.6;
    // front run: gap for the gate; infeed end (-X): gap where the stock comes in, guarded by a light curtain
    const runs = [[fx0, -fy, fx1, -fy, "gate"], [fx0, fy, fx1, fy], [fx0, -fy, fx0, fy, "curtain"], [fx1, -fy, fx1, fy]];
    for (const [x0, y0, x1, y1, gap] of runs) {
      const len = Math.hypot(x1 - x0, y1 - y0), n = Math.round(len / 2);
      for (let i = 0; i < n; i++) {
        if (gap === "gate" && i === Math.floor(n / 2)) continue;           // the gate opening
        if (gap === "curtain" && i === 0) continue;                        // the infeed opening
        const a = i / n, b = (i + 1) / n;
        const cx = x0 + (x1 - x0) * (a + b) / 2, cy = y0 + (y1 - y0) * (a + b) / 2;
        const panel = new THREE.Mesh(new THREE.PlaneGeometry(len / n - 0.06, 1.9), meshMat);
        panel.position.set(cx, cy, 1.1);
        panel.rotation.set(Math.PI / 2, Math.atan2(y1 - y0, x1 - x0), 0);
        this.scene.add(panel);
        this._box(0.06, 0.06, 2.1, 0, x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, 1.05, { material: fenceMat });
      }
    }
    const nFront = Math.round((fx1 - fx0) / 2);
    const gx = fx0 + (fx1 - fx0) * (Math.floor(nFront / 2) + 0.5) / nFront, gw = (fx1 - fx0) / nFront - 0.06;
    // interlocked gate (hinged on its left post) - swings open when the gate input opens
    this.gate = new THREE.Group();
    this.gate.position.set(gx - gw / 2, -fy, 0);
    const gatePanel = new THREE.Mesh(new THREE.PlaneGeometry(gw, 1.9), meshMat);
    gatePanel.rotation.x = Math.PI / 2;
    gatePanel.position.set(gw / 2, 0, 1.1);
    this.gate.add(gatePanel);
    for (const [w, h, x, z] of [[gw, 0.05, gw / 2, 2.05], [gw, 0.05, gw / 2, 0.15], [0.05, 1.95, gw - 0.03, 1.1]])
      this._box(w, 0.05, h, 0, x, 0, z, { parent: this.gate, material: fenceMat });
    this._box(0.08, 0.06, 0.12, 0xd91e18, gw - 0.1, -0.06, 1.1, { parent: this.gate });   // interlock switch
    this.scene.add(this.gate);
    // light curtain across the infeed opening: two posts and its beams
    const cy0 = -fy, cy1 = -fy + (2 * fy) / Math.round((2 * fy) / 2);
    for (const y of [cy0 + 0.05, cy1 - 0.05]) this._box(0.06, 0.06, 1.8, 0x111111, fx0 - 0.12, y, 0.9);
    this.beams = new THREE.Group();
    for (let z = 0.25; z <= 1.65; z += 0.07) {
      const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(fx0 - 0.12, cy0 + 0.05, z), new THREE.Vector3(fx0 - 0.12, cy1 - 0.05, z)]);
      this.beams.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xff3020, transparent: true, opacity: 0.18 })));
    }
    this.scene.add(this.beams);
    // operator desk and the camera mast (where the real camera watches the gate)
    this._box(1.2, 0.6, 0.9, 0x39424b, gx + 2.6, -fy - 1.1, 0.45);
    const screen = this._box(0.7, 0.04, 0.42, 0x0b1a2a, gx + 2.6, -fy - 1.0, 1.25, { noShadow: true });
    screen.rotation.x = -0.25;
    this._box(0.06, 0.06, 3.0, 0x39424b, gx - 1.6, -fy - 0.4, 1.5);
    this._box(0.16, 0.1, 0.1, 0x111111, gx - 1.6, -fy - 0.32, 2.95);
    // E-stop on the desk (yellow box, red mushroom head)
    this._box(0.12, 0.12, 0.08, 0xf2c230, gx + 2.15, -fy - 1.05, 0.94);
    const head = this._cyl(0.045, 0.04, 0xd91e18, { seg: 24 });
    head.rotation.x = Math.PI / 2;
    head.position.set(gx + 2.15, -fy - 1.05, 1.0);
    // stack light on a pole by the desk: red, amber, green, blue (top to bottom)
    this._box(0.04, 0.04, 1.2, 0x2b2f33, gx + 3.35, -fy - 1.0, 1.5);
    this.lamps = {};
    [["red", 0xff2a1f], ["amber", 0xffb000], ["green", 0x22d36b], ["blue", 0x2f7bff]].forEach(([name, colour], i) => {
      const mat = new THREE.MeshStandardMaterial({ color: colour, emissive: colour, emissiveIntensity: 0.05, transparent: true, opacity: 0.9 });
      const lamp = this._cyl(0.06, 0.11, 0, { material: mat });
      lamp.rotation.x = Math.PI / 2;
      lamp.position.set(gx + 3.35, -fy - 1.0, 2.6 - i * 0.12);
      this.lamps[name] = mat;
    });
  }

  // Show the safety state in the 3D cell: stack light, gate, light curtain.
  setSafety(st) {
    const blink = Math.floor(performance.now() / 500) % 2 === 0;
    for (const [name, mat] of Object.entries(this.lamps)) {
      const on = !!st.lamps[name] && (name !== "blue" || blink);
      mat.emissiveIntensity = on ? 2.2 : 0.05;
    }
    const open = !st.inputs.gate_closed;
    this.gate.rotation.z += ((open ? -1.4 : 0) - this.gate.rotation.z) * 0.5;
    const broken = !st.inputs.curtain_clear;
    this.beams.children.forEach((l) => { l.material.opacity = broken ? 0.95 : 0.18; });
  }

  // ---------------------------------------------------------------- a hand
  _hand(h) {
    const color = new THREE.Color(h.color);
    const paint = new THREE.MeshStandardMaterial({ color, metalness: 0.35, roughness: 0.45 });
    const dark = new THREE.MeshStandardMaterial({ color: C.housing, metalness: 0.5, roughness: 0.45 });
    const yellow = new THREE.MeshStandardMaterial({ color: C.bridge, metalness: 0.3, roughness: 0.5 });
    const W = this.m.width;
    const root = new THREE.Group();
    this.scene.add(root);
    // bridge: box girder spanning the rails, with end trucks and wheels
    const bridge = new THREE.Group();
    root.add(bridge);
    this._box(0.32, W + 0.5, 0.42, 0, 0, 0, 0.3, { parent: bridge, material: yellow });
    this._box(0.34, W + 0.52, 0.03, 0, 0, 0, 0.52, { parent: bridge, material: dark });
    for (const y of [-W / 2, W / 2]) {
      this._box(0.9, 0.24, 0.24, 0, 0, y, 0.08, { parent: bridge, material: yellow });
      for (const dx of [-0.32, 0.32]) {
        const wheel = this._cyl(0.09, 0.08, 0x222222, { parent: bridge, metal: 0.8 });
        wheel.position.set(dx, y, -0.02);
      }
      const motor = this._cyl(0.08, 0.22, 0x1d2329, { parent: bridge });
      motor.rotation.z = Math.PI / 2;
      motor.position.set(0.45, y + (y > 0 ? -0.18 : 0.18), 0.12);
    }
    // carriage on the bridge, column through it
    const carriage = new THREE.Group();
    root.add(carriage);
    this._box(0.62, 0.5, 0.36, 0, 0, 0, 0, { parent: carriage, material: dark });
    const cm = this._cyl(0.085, 0.3, 0x1d2329, { parent: carriage });
    cm.position.set(0, 0, 0.32);
    const label = this._box(0.63, 0.51, 0.06, 0, 0, 0, -0.12, { parent: carriage, material: paint });
    label.castShadow = false;
    const column = this._box(0.2, 0.2, 1, 0, 0, 0, 0, { material: paint });
    const columnInner = this._box(0.15, 0.15, 1, 0, 0, 0, 0, { material: dark });
    // arm: joint housings + links + tool
    const sc = h.a[1] ? Math.abs(h.a[1]) / 0.425 : 1;
    const r = 0.055 * sc;
    const housings = [], links = [];
    for (let i = 0; i < 6; i++) {
      const rr = r * (i < 3 ? 1.35 : 1.0);
      const m = new THREE.Mesh(new THREE.CylinderGeometry(rr, rr, rr * 2.3, 24), i % 2 ? paint : dark);
      m.castShadow = true;
      this.scene.add(m);
      housings.push(m);
    }
    for (let i = 0; i < 6; i++) {
      const rr = r * (i < 3 ? 1.0 : 0.75);
      const m = new THREE.Mesh(new THREE.CylinderGeometry(rr, rr, 1, 20), i === 0 ? dark : paint);
      m.castShadow = true;
      this.scene.add(m);
      links.push(m);
    }
    const tool = new THREE.Group();
    this.scene.add(tool);
    if (h.tool === "torch") {
      const body = this._cyl(0.022, 0.26, 0x1a1a1a, { parent: tool, metal: 0.6 });
      body.position.y = 0.13;
      const sleeve = this._cyl(0.03, 0.06, 0x3a3a3a, { parent: tool });
      sleeve.position.y = 0.02;
      const nozzle = this._cyl(0.006, 0.04, 0xb87333, { parent: tool, r2: 0.016, metal: 0.9, rough: 0.25 });
      nozzle.position.y = 0.28;
    } else {
      const stem = this._cyl(0.03, 0.09, 0x5d6d7e, { parent: tool });
      stem.position.y = 0.045;
      const pad = this._cyl(0.11, 0.03, 0xb22222, { parent: tool, seg: 32 });
      pad.position.y = 0.105;
    }
    return { cfg: h, root, bridge, carriage, column, columnInner, housings, links, tool, tip: new THREE.Vector3(), dir: new THREE.Vector3(), r };
  }

  // Put a hand at gantry g and joints q.
  pose(key, g, q) {
    const H = this.hands[key], rz = this.m.rail_z;
    H.bridge.position.set(g[0], 0, rz);
    H.carriage.position.set(g[0], g[1], rz - 0.12);
    const top = rz - 0.3, len = Math.max(top - g[2], 0.05);
    H.column.scale.z = len;
    H.column.position.set(g[0], g[1], g[2] + len / 2);
    H.columnInner.scale.z = len + 0.1;
    H.columnInner.position.set(g[0], g[1], g[2] + len / 2 - 0.05);
    const F = handFrames(H.cfg, g, q);
    const P = F.map((f) => new THREE.Vector3().setFromMatrixPosition(f));
    const Z = F.map((f) => new THREE.Vector3().setFromMatrixColumn(f, 2));
    const up = new THREE.Vector3(0, 1, 0);
    for (let i = 0; i < 6; i++) {
      H.housings[i].position.copy(P[i]);
      H.housings[i].quaternion.setFromUnitVectors(up, Z[i]);
      const a = P[i], b = P[i + 1], d = new THREE.Vector3().subVectors(b, a), L = d.length();
      H.links[i].visible = L > 1e-4;
      if (L > 1e-4) {
        H.links[i].position.copy(a).addScaledVector(d, 0.5);
        H.links[i].quaternion.setFromUnitVectors(up, d.normalize());
        H.links[i].scale.set(1, L, 1);
      }
    }
    H.tool.position.copy(P[6]);
    H.tool.quaternion.setFromUnitVectors(up, Z[6]);
    H.tip.copy(P[7]);
    H.dir.copy(Z[7]);
  }

  // ---------------------------------------------------------------- effects
  _effects() {
    this.arc = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.0015, 0.03, 8),
      new THREE.MeshBasicMaterial({ color: 0xc8e6ff }));
    this.arc.visible = false;
    this.scene.add(this.arc);
    this.glow = new THREE.PointLight(0xffa040, 0, 1.6, 1.5);
    this.scene.add(this.glow);
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
    this.renderer.render(this.scene, this.camera);
  }
}

// I-section outline (mm) for the building's own steelwork
export function ubOutline(h, b, tw, tf, r) {
  const pts = [[-b / 2, 0], [b / 2, 0], [b / 2, tf]];
  const arc = (cx, cy, a0, a1) => { for (let i = 0; i <= 6; i++) { const a = a0 + (a1 - a0) * i / 6; pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); } };
  arc(tw / 2 + r, tf + r, -Math.PI / 2, -Math.PI);
  arc(tw / 2 + r, h - tf - r, Math.PI, Math.PI / 2);
  pts.push([b / 2, h - tf], [b / 2, h], [-b / 2, h], [-b / 2, h - tf]);
  arc(-tw / 2 - r, h - tf - r, Math.PI / 2, 0);
  arc(-tw / 2 - r, tf + r, 0, -Math.PI / 2);
  pts.push([-b / 2, tf]);
  return pts;
}
