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
    const chainMat = new THREE.MeshStandardMaterial({ color: 0x23272b, roughness: 0.7, metalness: 0.1 });
    const linkGeo = new THREE.BoxGeometry(LINK * 0.92, 0.12, 0.045);
    const crossGeo = new THREE.BoxGeometry(0.09, LINK * 0.92, 0.035);
    this.hands = {};
    for (const [key, side] of [["cutter", -1], ["handler", 1]]) {
      const run = new THREE.InstancedMesh(linkGeo, chainMat, this.maxLinks);
      const cross = new THREE.InstancedMesh(crossGeo, chainMat, Math.ceil(3.4 / LINK) + 40);
      const riser = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.05, 1), chainMat);
      const bracket = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.35, 0.04), new THREE.MeshStandardMaterial({ color: 0xf2c230 }));
      for (const o of [run, cross, riser, bracket]) { o.castShadow = true; o.frustumCulled = false; scene.add(o); }
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
      this.hands[key] = { side, run, cross, riser, bracket, tubes, last: null };
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
      const curve = new THREE.CatmullRomCurve3(p, false, "centripetal");
      t.mesh.geometry.dispose();
      t.mesh.geometry = new THREE.TubeGeometry(curve, 90, t.r, 7, false);
    }
  }
}
