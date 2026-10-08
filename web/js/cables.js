// The cables that move with the machine (the fixed ones - trays, the plasma power source, the
// control cabinet - are in the CAD model, beamcell/cad.py):
//   - an ENERGY CHAIN along a runway for each bridge (Cutter on the front runway, Handler on the back),
//     fixed in the middle of the travel and folding as the bridge runs: lower run in its tray, a loop,
//     upper run back to the bridge's end truck;
//   - a CROSS CHAIN on top of each bridge to its carriage (the Y axis);
//   - the DRESS PACK down each mast and along each arm: torch lead + gas hose to the plasma torch,
//     power cable to the magnet.
import * as THREE from "three";
import { handFrames } from "./kinematics.js";

const LINK = 0.065;                       // energy chain link pitch (m)

// Merge simple geometries (position + normal + index) into one, so a chain link is one instance.
function merge(geoms) {
  const pos = [], nor = [], idx = [];
  let base = 0;
  for (const g0 of geoms) {
    const g = g0.index ? g0 : g0.toNonIndexed();
    const p = g.attributes.position.array, n = g.attributes.normal.array;
    pos.push(...p); nor.push(...n);
    if (g.index) for (const i of g.index.array) idx.push(i + base);
    else for (let i = 0; i < p.length / 3; i++) idx.push(i + base);
    base += p.length / 3;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  out.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  out.setIndex(idx);
  return out;
}

// One energy-chain link (igus E4 style): two moulded side plates with rounded ends and the pin boss,
// joined by a crossbar top and bottom. Length along X, width across Y, height in Z; centred.
function chainLink(width, height) {
  const L = LINK * 1.18, r = height / 2;
  const sh = new THREE.Shape();
  sh.moveTo(-L / 2 + r, -r); sh.lineTo(L / 2 - r, -r); sh.absarc(L / 2 - r, 0, r, -Math.PI / 2, Math.PI / 2);
  sh.lineTo(-L / 2 + r, r); sh.absarc(-L / 2 + r, 0, r, Math.PI / 2, 1.5 * Math.PI);
  const t = 0.006, parts = [];
  for (const side of [-1, 1]) {
    const plate = new THREE.ExtrudeGeometry(sh, { depth: t, bevelEnabled: false, curveSegments: 6 });
    plate.rotateX(Math.PI / 2);
    plate.translate(0, side * (width / 2) + (side < 0 ? t : 0), 0);
    parts.push(plate);
    const boss = new THREE.CylinderGeometry(r * 0.45, r * 0.45, t * 1.6, 12);
    boss.translate(L / 2 - r, side * (width / 2 + t * 0.3), 0);
    parts.push(boss);
  }
  for (const z of [-r + 0.004, r - 0.004]) {
    const bar = new THREE.BoxGeometry(L * 0.55, width, 0.008);
    bar.translate(0, 0, z);
    parts.push(bar);
  }
  return merge(parts);
}

// Points [along, height, angle] of a folded energy chain: fixed end at `fix` (the middle of the travel),
// moving end at `move`, never below `lo`. The loop sits halfway between `lo` and the moving end, so the
// chain is fully stretched when the axis is at the far end and fully folded at the near end.
function chainPath(fix, move, lo, R) {
  const loop = (move + lo) / 2;
  const pts = [];
  for (let s = 0; s <= move - loop + 1e-9; s += LINK) pts.push([move - s, 2 * R, 0]);              // upper run
  for (let a = Math.PI / 2 + LINK / R; a < 1.5 * Math.PI; a += LINK / R) {                         // the loop
    pts.push([loop + R * Math.cos(a), R + R * Math.sin(a), a - Math.PI / 2]);
  }
  for (let s = 0; s <= fix - loop + 1e-9; s += LINK) pts.push([loop + s, 0, Math.PI]);             // lower run
  return pts;
}

export class Cables {
  constructor(scene, machine) {
    this.scene = scene;
    this.m = machine;
    const [xa, xb] = machine.x_limits;
    this.xa = xa;
    this.xFix = (xa + xb) / 2;
    this.maxLinks = Math.ceil((xb - xa + 1) / LINK) + 40;
    const chainMat = new THREE.MeshStandardMaterial({ color: 0x2a2d31, roughness: 0.55, metalness: 0.05 });
    const linkGeo = chainLink(0.125, 0.05);                // runway chains: 125 wide, 50 high (igus E4.56 class)
    const crossGeo = chainLink(0.09, 0.04);                // cross chains on the bridges
    crossGeo.rotateZ(Math.PI / 2);                         // they run across (Y)
    const steelMat = new THREE.MeshStandardMaterial({ color: 0x9aa1a8, roughness: 0.4, metalness: 0.6 });
    const clampMat = new THREE.MeshStandardMaterial({ color: 0x111315, roughness: 0.6 });
    this.hands = {};
    for (const [key, side] of [["cutter", -1], ["handler", 1]]) {
      const run = new THREE.InstancedMesh(linkGeo, chainMat, this.maxLinks);
      const cross = new THREE.InstancedMesh(crossGeo, chainMat, Math.ceil(3.4 / LINK) + 40);
      const riser = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1, 16).rotateX(Math.PI / 2), steelMat);   // flexible conduit
      // chain end bracket: a folded steel angle from the end truck out to the chain
      const bracket = new THREE.Mesh(merge([new THREE.BoxGeometry(0.1, 0.35, 0.006),
        new THREE.BoxGeometry(0.1, 0.006, 0.06).translate(0, 0.172, -0.03)]), steelMat);
      const clamps = new THREE.InstancedMesh(new THREE.TorusGeometry(0.03, 0.007, 6, 14), clampMat, 16);
      for (const o of [run, cross, riser, bracket, clamps]) { o.castShadow = true; o.frustumCulled = false; scene.add(o); }
      const pack = key === "cutter"
        ? [{ r: 0.016, color: 0x15181b, off: 0.07 }, { r: 0.008, color: 0x2563eb, off: 0.1 }]       // torch lead, gas hose
        : [{ r: 0.02, color: 0x6b7280, off: 0.09 }];                                                // magnet power cable
      const tubes = pack.map((p) => {
        const mesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshStandardMaterial({ color: p.color, roughness: 0.55 }));
        mesh.castShadow = true;
        mesh.frustumCulled = false;
        scene.add(mesh);
        return { ...p, mesh };
      });
      this.hands[key] = { side, run, cross, riser, bracket, clamps, tubes, last: null };
    }
    this._m4 = new THREE.Matrix4();
    this._q = new THREE.Quaternion();
    this._v = new THREE.Vector3();
    this._s = new THREE.Vector3(1, 1, 1);
  }

  // Follow one hand at gantry g, joints q (called with the same values as scene.pose).
  update(key, cfg, g, q) {
    const C = this.hands[key];
    const sig = g.join(",") + q.join(",");
    if (C.last === sig) return;
    C.last = sig;
    const rz = this.m.rail_z, W = this.m.width;
    // runway energy chain, beside the runway on the outside
    const y = C.side * (W / 2 + 0.35), zl = rz - 0.07, R = 0.12;
    const pts = chainPath(this.xFix, g[0], this.xa, R);
    const n = Math.min(pts.length, C.run.count);
    for (let i = 0; i < n; i++) {
      const [x, h, a] = pts[i];
      this._q.setFromAxisAngle(this._v.set(0, 1, 0), -a);
      this._m4.compose(this._v.set(x, y, zl + h), this._q, this._s);
      C.run.setMatrixAt(i, this._m4);
    }
    for (let i = n; i < C.run.count; i++) { this._m4.makeScale(0, 0, 0); C.run.setMatrixAt(i, this._m4); }
    C.run.instanceMatrix.needsUpdate = true;
    C.bracket.position.set(g[0], C.side * (W / 2 + 0.18), zl + 2 * R);
    // cross chain on top of the bridge, to the carriage
    const top = rz + 0.57, r = 0.08;
    const cpts = chainPath(0, g[1], -1.45, r);
    const m = Math.min(cpts.length, C.cross.count);
    for (let i = 0; i < m; i++) {
      const [s, h, a] = cpts[i];
      this._q.setFromAxisAngle(this._v.set(1, 0, 0), a);
      this._m4.compose(this._v.set(g[0] + 0.24, s, top + h), this._q, this._s);
      C.cross.setMatrixAt(i, this._m4);
    }
    for (let i = m; i < C.cross.count; i++) { this._m4.makeScale(0, 0, 0); C.cross.setMatrixAt(i, this._m4); }
    C.cross.instanceMatrix.needsUpdate = true;
    // riser from the cross chain down to the carriage
    const h = top + 2 * r - (rz - 0.12);
    C.riser.scale.set(1, 1, h);
    C.riser.position.set(g[0] + 0.24, g[1], rz - 0.12 + h / 2);
    // dress pack: carriage -> top of the mast -> down the mast -> along the arm -> the tool
    const F = handFrames(cfg, g, q);
    for (const t of C.tubes) {
      const p = [new THREE.Vector3(g[0] + 0.24, g[1], rz - 0.1), new THREE.Vector3(g[0] + t.off, g[1], g[2] + 2.05),
        new THREE.Vector3(g[0] + t.off + 0.03, g[1], g[2] + 1.0), new THREE.Vector3(g[0] + t.off, g[1], g[2] + 0.1)];
      for (let k = 1; k <= 6; k++) {
        const o = new THREE.Vector3().setFromMatrixPosition(F[k]);
        const side = new THREE.Vector3().setFromMatrixColumn(F[k], 1).multiplyScalar(t.off);
        p.push(o.add(side));
      }
      p.push(new THREE.Vector3().setFromMatrixPosition(F[7]).add(new THREE.Vector3().setFromMatrixColumn(F[7], 2).multiplyScalar(-0.25))
        .add(new THREE.Vector3().setFromMatrixColumn(F[7], 1).multiplyScalar(0.04)));
      if (t === C.tubes[0]) {                                    // dress-pack clamps hold the bundle at each link
        for (let k = 0; k < 16; k++) {
          const i = 3 + Math.floor(k / 2);
          if (i >= p.length - 1) { this._m4.makeScale(0, 0, 0); C.clamps.setMatrixAt(k, this._m4); continue; }
          const a = p[i], b = p[i + 1], u = (k % 2) * 0.5 + 0.25;
          const at = a.clone().lerp(b, u), dir = b.clone().sub(a).normalize();
          this._q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir);
          this._m4.compose(at, this._q, this._s);
          C.clamps.setMatrixAt(k, this._m4);
        }
        C.clamps.instanceMatrix.needsUpdate = true;
      }
      const curve = new THREE.CatmullRomCurve3(p, false, "centripetal");
      t.mesh.geometry.dispose();
      t.mesh.geometry = new THREE.TubeGeometry(curve, 90, t.r, 7, false);
    }
  }
}
