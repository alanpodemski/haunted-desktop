// The handheld flashlight: a shadow-casting spotlight held just below and right of the eye, aimed where the cursor
// points in the room. The hand is a damped spring with a little tremor, so the beam lags and settles like a real
// arm. A second, shadowless light at the beam's hit point stands in for the light bouncing off the lit surface.

import * as THREE from 'three';
import { castRoom } from './layout.js';

/** Beam profile of a cheap reflector torch: hot centre, a bright reflector ring, dimmer corona, faint spill. */
function cookieTexture(size = 512) {
  const c = document.createElement('canvas'); c.width = c.height = size;
  const g = c.getContext('2d');
  const img = g.createImageData(size, size);
  const rnd = (i) => { const x = Math.sin(i * 127.1) * 43758.5453; return x - Math.floor(x); };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const u = (x + 0.5) / size * 2 - 1, v = (y + 0.5) / size * 2 - 1;
      const r = Math.hypot(u, v);
      const a = Math.atan2(v, u);
      let I = 0.065 * Math.pow(Math.max(0, 1 - r), 0.6);                     // spill
      I += 0.38 * Math.exp(-Math.pow(r / 0.42, 4));                           // corona
      I += 0.55 * Math.exp(-Math.pow(r / 0.17, 2.2));                         // hotspot
      I += 0.08 * Math.exp(-Math.pow((r - 0.45) / 0.03, 2));                  // reflector ring
      I *= 1 - 0.18 * Math.exp(-Math.pow(r / 0.035, 2));                      // the bulb's own shadow
      // reflector imperfections: faint concentric rings and petals
      I *= 1 + 0.05 * Math.sin(r * 90 + rnd(3) * 6) * Math.exp(-r * 2) + 0.025 * Math.sin(a * 7 + r * 12);
      I *= r < 0.98 ? 1 : Math.max(0, (1 - r) / 0.02);
      const i = (y * size + x) * 4;
      // slight warm centre, cooler edge (cheap incandescent / warm LED)
      img.data[i] = Math.min(255, I * 255 * 1.0);
      img.data[i + 1] = Math.min(255, I * 255 * (0.93 + 0.03 * r));
      img.data[i + 2] = Math.min(255, I * 255 * (0.8 + 0.12 * r));
      img.data[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// smooth 1D value noise for hand tremor
function noise1(t, seed) {
  const i = Math.floor(t), f = t - i;
  const h = (n) => { const x = Math.sin((n + seed * 57.3) * 12.9898) * 43758.5453; return x - Math.floor(x); };
  const s = f * f * (3 - 2 * f);
  return (h(i) * (1 - s) + h(i + 1) * s) * 2 - 1;
}

export function createFlashlight(scene, camera, { candela = 90, angle = 0.62 } = {}) {
  const spot = new THREE.SpotLight(0xfff1dc, candela, 0, angle, 0.08, 2);
  spot.map = cookieTexture();
  spot.castShadow = true;
  spot.shadow.mapSize.set(2048, 2048);
  spot.shadow.camera.near = 0.08;
  spot.shadow.camera.far = 14;
  spot.shadow.bias = -0.00012;
  spot.shadow.normalBias = 0.018;
  spot.shadow.radius = 3;
  scene.add(spot, spot.target);

  // bounce: Lambertian re-emission of the flux the beam puts on the surface it hits
  const bounce = new THREE.PointLight(0xd9c4a6, 0, 0, 2);
  scene.add(bounce);

  // the hand: right of and below the eye, a little forward
  const handOffset = new THREE.Vector3(0.2, -0.26, -0.12);
  const eye = camera.position.clone();
  const hand = eye.clone().add(handOffset);

  const ndc = new THREE.Vector2(0.02, 0.05);
  let yaw = 0, pitch = 0, vyaw = 0, vpitch = 0, initialised = false;
  let on = true, level = 1, flicker = 0, t = 0;
  const ray = new THREE.Raycaster();
  const dir = new THREE.Vector3();
  const tmp = new THREE.Vector3();

  function desiredAngles() {
    ray.setFromCamera(ndc, camera);
    const o = ray.ray.origin, d = ray.ray.direction;
    const hit = castRoom([o.x, o.y, o.z], [d.x, d.y, d.z]);
    // aim from the hand at the point under the cursor, so the hotspot lands on the cursor
    tmp.set(hit.point[0], hit.point[1], hit.point[2]).sub(hand).normalize();
    return { yaw: Math.atan2(tmp.x, -tmp.z), pitch: Math.asin(THREE.MathUtils.clamp(tmp.y, -1, 1)) };
  }

  return {
    spot, bounce,
    get on() { return on; },
    /** cursor in normalised device coordinates */
    setPointer(x, y) { ndc.set(x, y); },
    aimAt(p, snap = false) {
      tmp.copy(p).project(camera); ndc.set(tmp.x, tmp.y);
      if (snap) initialised = false;     // jump there this frame instead of swinging the arm
    },
    toggle(v = !on) { on = v; return on; },
    /** brief brown-out (the creature is close, or the batteries are old) */
    stutter(seconds = 0.6) { flicker = Math.max(flicker, seconds); },
    /** unit direction of the beam axis and where the light sits */
    get dir() { return dir; },
    get pos() { return spot.position; },
    /** 0..1: how lit a world point is (cone falloff only, no shadows) */
    exposure(p) {
      if (!on || level < 0.05) return 0;
      tmp.copy(p).sub(spot.position);
      const d = tmp.length(); tmp.divideScalar(d);
      const c = tmp.dot(dir);
      const r = Math.acos(THREE.MathUtils.clamp(c, -1, 1)) / spot.angle; // 0 centre .. 1 cone edge
      if (r >= 1) return 0;
      return level * (0.06 + 0.94 * Math.exp(-Math.pow(r / 0.42, 3))) * Math.min(1, 9 / (d * d));
    },
    update(dt) {
      t += dt;
      const want = desiredAngles();
      if (!initialised) { yaw = want.yaw; pitch = want.pitch; initialised = true; }
      // damped spring (arm + torch ≈ 0.4 kg at ~0.5 m: settles in ~0.25 s, a hint of overshoot)
      const k = 120, c = 17;
      let dy = want.yaw - yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
      vyaw += (k * dy - c * vyaw) * dt; yaw += vyaw * dt;
      vpitch += (k * (want.pitch - pitch) - c * vpitch) * dt; pitch += vpitch * dt;
      // physiological tremor (~8–12 Hz, tiny) and slow postural drift
      const tremor = 0.0012, drift = 0.006;
      const ty = yaw + tremor * noise1(t * 10, 1) + drift * noise1(t * 0.35, 2);
      const tp = pitch + tremor * noise1(t * 11, 3) + drift * noise1(t * 0.3, 4);
      dir.set(Math.sin(ty) * Math.cos(tp), Math.sin(tp), -Math.cos(ty) * Math.cos(tp));
      // breathing moves the hand a few millimetres
      spot.position.copy(hand).addScaledVector(camera.up, 0.004 * Math.sin(t * 1.6));
      spot.position.addScaledVector(dir, 0.03);
      spot.target.position.copy(spot.position).addScaledVector(dir, 3);
      spot.target.updateMatrixWorld();

      // brown-outs: the filament dims and recovers unevenly
      let target = on ? 1 : 0;
      if (flicker > 0) {
        flicker -= dt;
        const n = noise1(t * 38, 7);
        target *= n > 0.25 ? 0.06 : 0.55 + 0.45 * Math.abs(noise1(t * 13, 8));
      }
      level += (target - level) * Math.min(1, dt * (on ? 40 : 60));
      spot.intensity = candela * level;

      // bounce light: hit point of the beam axis, re-emitted as a Lambertian source
      const h = castRoom([spot.position.x, spot.position.y, spot.position.z], [dir.x, dir.y, dir.z]);
      const albedo = h.inCorridor ? 0.22 : 0.3;
      const beamSolidAngle = Math.PI * Math.pow(spot.angle * 0.55, 2);    // where most of the cookie's energy is
      const flux = spot.intensity * beamSolidAngle * 0.55;                 // cookie average ≈ 0.55
      bounce.intensity = 0.6 * albedo * flux / Math.PI;   // 0.6: part of the patch lies beyond the beam axis hit and much of the room absorbs
      // the lit patch is a disc, not a point: put the stand-in source about one patch radius off the surface so it
      // has no hot singularity on the wall it comes from
      const off = Math.max(0.5, h.dist * Math.tan(spot.angle * 0.55));
      bounce.position.set(h.point[0] + h.normal[0] * off, h.point[1] + h.normal[1] * off, h.point[2] + h.normal[2] * off);
    },
  };
}
