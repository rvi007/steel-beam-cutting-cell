// Steel shapes for the 3D view, built from the exact UK section outlines.
//   - plain stock (offcuts, remnant, the library preview): the section outline pulled along X
//   - parts: plate by plate (flanges, web, legs) from each face's outline, with the holes and
//     notches cut right through, plus the root-radius fillets between plates
// Machine coordinates: X along the bar, Y across, Z up, metres. Section/face sizes are in mm.
import * as THREE from "three";

export const MAT = {
  // mill-scale steel is dull blue-grey, not a mirror: low metalness reads right from every side
  steel: new THREE.MeshStandardMaterial({ color: 0x86909a, metalness: 0.3, roughness: 0.6 }),
  done: new THREE.MeshStandardMaterial({ color: 0x86929c, metalness: 0.35, roughness: 0.5 }),
  scrap: new THREE.MeshStandardMaterial({ color: 0x6d5f52, metalness: 0.3, roughness: 0.7 }),
  library: new THREE.MeshStandardMaterial({ color: 0x8e979f, metalness: 0.4, roughness: 0.45 }),
};

const ALONG_X = new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0));

// ---------------------------------------------------------------- 2D helpers (mm)
export function faceToSection(sec, face, y) {
  return face === "v" || face === "h" ? y : sec.b / 2 - y;
}

export function clipBand(poly, y0, y1) {
  const clip = (pts, keep, cross) => {
    const out = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[(i - 1 + pts.length) % pts.length], b = pts[i];
      if (keep(b)) { if (!keep(a)) out.push(cross(a, b)); out.push(b); }
      else if (keep(a)) out.push(cross(a, b));
    }
    return out;
  };
  const atY = (yc) => (a, b) => [a[0] + (yc - a[1]) * (b[0] - a[0]) / (b[1] - a[1]), yc];
  let p = clip(poly, (q) => q[1] >= y0 - 1e-9, atY(y0));
  return p.length ? clip(p, (q) => q[1] <= y1 + 1e-9, atY(y1)) : [];
}

export function clipX(poly, x0, x1) {
  const swap = (pts) => pts.map(([a, b]) => [b, a]);
  return swap(clipBand(swap(poly), x0, x1));
}

export function intervalsAt(poly, y) {
  const xs = [];
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    if ((y1 > y) !== (y2 > y)) xs.push(x1 + (y - y1) * (x2 - x1) / (y2 - y1));
  }
  xs.sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i + 1 < xs.length; i += 2) out.push([xs[i], xs[i + 1]]);
  return out;
}

function intersect(a, b) {
  const out = [];
  for (const [a0, a1] of a) for (const [b0, b1] of b) {
    const lo = Math.max(a0, b0), hi = Math.min(a1, b1);
    if (hi - lo > 0.5) out.push([lo, hi]);
  }
  return out;
}

// Outline of a hole or slot in face coordinates (mm).
export function holeOutline(h, steps = 28) {
  const r = h.d / 2, straight = Math.max((h.slot || 0) - h.d, 0) / 2, a = ((h.angle || 0) * Math.PI) / 180;
  const pts = [];
  if (straight <= 0) {
    for (let i = 0; i < steps; i++) pts.push([r * Math.cos((2 * Math.PI * i) / steps), r * Math.sin((2 * Math.PI * i) / steps)]);
  } else {
    for (let i = 0; i <= steps / 2; i++) { const t = -Math.PI / 2 + (Math.PI * i) / (steps / 2); pts.push([straight + r * Math.cos(t), r * Math.sin(t)]); }
    for (let i = 0; i <= steps / 2; i++) { const t = Math.PI / 2 + (Math.PI * i) / (steps / 2); pts.push([-straight + r * Math.cos(t), r * Math.sin(t)]); }
  }
  const c = Math.cos(a), s = Math.sin(a);
  return pts.map(([x, y]) => [h.x + x * c - y * s, h.y + x * s + y * c]);
}

function normFace(sec, face) {
  if (face === "h") return "v";
  if (sec.kind === "L" && face !== "v" && face !== "u") return "u";
  return face;
}

// ---------------------------------------------------------------- shapes
function shapeFrom(points, holes = []) {
  const shape = new THREE.Shape(points.map(([x, y]) => new THREE.Vector2(x, y)));
  for (const h of holes) shape.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
  return shape;
}

// A section (or a piece of plain stock) pulled along X from x0 to x1 (mm).
export function stockMesh(section, x0, x1, material, origin) {
  const outer = section.outline.map(([u, v]) => [u / 1000, v / 1000]);
  const holes = (section.holes || []).map((h) => h.map(([u, v]) => [u / 1000, v / 1000]));
  const geo = new THREE.ExtrudeGeometry(shapeFrom(outer, holes), { depth: (x1 - x0) / 1000, bevelEnabled: false, curveSegments: 6 });
  geo.applyMatrix4(ALONG_X);
  const mesh = new THREE.Mesh(geo, material);
  mesh.position.set(origin.x + x0 / 1000, origin.y, origin.z);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

// Fillet (root radius) between two plates: corner (u, v), opening towards (su, sv).
function filletShape(cu, cv, r, su, sv) {
  const pts = [[cu, cv], [cu + su * r, cv]];
  for (let i = 1; i < 6; i++) {
    const t = (Math.PI / 2) * (i / 6);
    pts.push([cu + su * r - su * r * Math.sin(t), cv + sv * r - sv * r * Math.cos(t)]);
  }
  pts.push([cu, cv + sv * r]);
  return pts.map(([u, v]) => [u / 1000, v / 1000]);
}

function junctions(sec) {
  const { h, b, tw, tf } = sec;
  if (sec.kind === "I") return [[tw / 2, tf, 1, 1], [-tw / 2, tf, -1, 1], [tw / 2, h - tf, 1, -1], [-tw / 2, h - tf, -1, -1]]
    .map(([u, v, su, sv]) => ({ u, v, su, sv, r: sec.r, up: "v", flat: sv > 0 ? "u" : "o" }));
  if (sec.kind === "U") return [[b / 2 - tw, tf, -1, 1], [b / 2 - tw, h - tf, -1, -1]]
    .map(([u, v, su, sv]) => ({ u, v, su, sv, r: sec.r, up: "v", flat: sv > 0 ? "u" : "o" }));
  if (sec.kind === "L") return [{ u: b / 2 - sec.t, v: sec.t, su: -1, sv: 1, r: sec.r1, up: "v", flat: "u" }];
  return [];
}

// ---------------------------------------------------------------- a part, plate by plate
// view: one placement from /api/plan (part, section, faces, x0)
// state: { start: bool, end: bool, holes: Set, openings: Set } - what has been cut so far
export function partGroup(view, state, material, origin) {
  const sec = view.section, part = view.part, L = part.length;
  const group = new THREE.Group();
  const split = splitPoint(part, L);
  const rect = (W) => [[0, 0], [L, 0], [L, W], [0, W]];
  const shown = {};                                     // face -> [polygon per half]
  for (const pl of sec.plates) {
    const face = pl.face;
    const W = face === "v" ? sec.h : sec.b;
    const final = view.faces[face], plain = rect(W);
    const halves = [clipX(state.start ? final : plain, -1, split), clipX(state.end ? final : plain, split, L + 1)];
    shown[face] = [];
    for (const half of halves) {
      let poly = pl.flat ? half : clipBand(half, pl.v0, pl.v1);
      if (poly.length < 3) continue;
      shown[face].push(poly);
      const [hx0, hx1] = [Math.min(...poly.map((p) => p[0])), Math.max(...poly.map((p) => p[0]))];
      const holes = [];
      part.holes.forEach((hole, i) => {
        if (!state.holes.has(i) || normFace(sec, hole.face) !== face) return;
        if (hole.x < hx0 || hole.x > hx1) return;
        holes.push(holeOutline(hole));
      });
      (part.inner || []).forEach((item, i) => {
        if (!state.openings.has(i) || normFace(sec, item.face) !== face) return;
        const cx = item.points.reduce((s, p) => s + p[0], 0) / item.points.length;
        if (cx >= hx0 && cx <= hx1) holes.push(item.points);
      });
      // plate's own 2D coordinates: (x, u) for flat plates, (x, v) for upright ones
      const map = pl.flat ? ([x, y]) => [x / 1000, faceToSection(sec, face, y) / 1000] : ([x, y]) => [x / 1000, y / 1000];
      const outline = poly.map(map), holeLoops = holes.map((hl) => hl.map(map));
      const depth = (pl.flat ? pl.v1 - pl.v0 : pl.u1 - pl.u0) / 1000;
      const geo = new THREE.ExtrudeGeometry(shapeFrom(outline, holeLoops), { depth, bevelEnabled: false, curveSegments: 8 });
      const mesh = new THREE.Mesh(geo, material);
      if (pl.flat) mesh.position.set(origin.x + view.x0 / 1000, origin.y, origin.z + pl.v0 / 1000);
      else { mesh.rotation.x = Math.PI / 2; mesh.position.set(origin.x + view.x0 / 1000, origin.y + pl.u1 / 1000, origin.z); }
      mesh.castShadow = mesh.receiveShadow = true;
      group.add(mesh);
    }
  }
  // root-radius fillets where both plates are present
  for (const j of junctions(sec)) {
    if (!shown[j.up] || !shown[j.flat]) continue;
    const upIv = shown[j.up].flatMap((p) => intervalsAt(p, j.v + j.sv * 0.5));
    const flatIv = shown[j.flat].flatMap((p) => intervalsAt(p, sec.b / 2 - (j.u + j.su * 0.5)));
    for (const [x0, x1] of intersect(upIv, flatIv)) {
      const geo = new THREE.ExtrudeGeometry(shapeFrom(filletShape(j.u, j.v, j.r, j.su, j.sv)), { depth: (x1 - x0) / 1000, bevelEnabled: false });
      geo.applyMatrix4(ALONG_X);
      const mesh = new THREE.Mesh(geo, material);
      mesh.position.set(origin.x + (view.x0 + x0) / 1000, origin.y, origin.z);
      mesh.castShadow = true;
      group.add(mesh);
    }
  }
  return group;
}

// Split each plate in two (start half / end half) somewhere near the middle, not through a hole.
function splitPoint(part, L) {
  let x = L / 2;
  for (let tries = 0; tries < 40; tries++) {
    const hit = part.holes.some((h) => Math.abs(h.x - x) < Math.max(h.slot || 0, h.d) / 2 + 2) ||
      (part.inner || []).some((it) => { const xs = it.points.map((p) => p[0]); return x > Math.min(...xs) - 2 && x < Math.max(...xs) + 2; });
    if (!hit) return x;
    x += (tries % 2 ? -1 : 1) * 15 * (tries + 1);
  }
  return L / 2;
}

export function disposeGroup(obj) {
  obj.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
  if (obj.parent) obj.parent.remove(obj);
}
