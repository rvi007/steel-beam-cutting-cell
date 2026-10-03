// Arm kinematics in the browser - the same maths as beamcell/arm.py and machine.py,
// so the 3D view shows exactly what the planner worked out.
import * as THREE from "three";

function dh(a, d, alpha, theta) {
  const ct = Math.cos(theta), st = Math.sin(theta), ca = Math.cos(alpha), sa = Math.sin(alpha);
  return new THREE.Matrix4().set(
    ct, -st * ca, st * sa, a * ct,
    st, ct * ca, -ct * sa, a * st,
    0, sa, ca, d,
    0, 0, 0, 1);
}

// World frames of one hand: base, 6 joints, tool tip. g = gantry [x, y, z], q = 6 joint angles.
export function handFrames(hand, g, q) {
  // the arm hangs upside down under the column: X stays, Y and Z flip
  const base = new THREE.Matrix4().set(1, 0, 0, g[0], 0, -1, 0, g[1], 0, 0, -1, g[2], 0, 0, 0, 1);
  const frames = [base.clone()];
  let T = base.clone();
  for (let i = 0; i < 6; i++) {
    T = T.clone().multiply(dh(hand.a[i], hand.d[i], hand.alpha[i], q[i]));
    frames.push(T);
  }
  const tip = T.clone().multiply(new THREE.Matrix4().makeTranslation(0, 0, hand.tool_length));
  frames.push(tip);
  return frames;
}

// Value of a recorded track at time t (linear between samples).
export function trackAt(track, t) {
  const T = track.t;
  let lo = 0, hi = T.length - 1;
  if (t <= T[0]) return [track.g[0], track.q[0]];
  if (t >= T[hi]) return [track.g[hi], track.q[hi]];
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (T[mid] <= t) lo = mid; else hi = mid;
  }
  const f = (t - T[lo]) / Math.max(T[hi] - T[lo], 1e-9);
  const g = track.g[lo].map((v, i) => v + f * (track.g[hi][i] - v));
  const q = track.q[lo].map((v, i) => v + f * (track.q[hi][i] - v));
  return [g, q];
}
