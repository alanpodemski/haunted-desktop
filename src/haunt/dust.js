// Dust in the air. Each mote drifts on slow air currents and settles under gravity at its terminal velocity; it is
// only visible where the flashlight's cone passes through it (forward scattering makes motes near the beam axis,
// seen against the light, the brightest).

import * as THREE from 'three';
import { HALL } from './layout.js';

export function createDust(scene, flashlight, count = 1600) {
  const pos = new Float32Array(count * 3);
  const seed = new Float32Array(count);
  const box = { x0: HALL.x0 + 0.1, x1: HALL.x1 - 0.1, y0: 0.05, y1: 2.8, z0: -8, z1: 0.2 };   // the near half of the hallway
  for (let i = 0; i < count; i++) {
    pos[i * 3] = box.x0 + Math.random() * (box.x1 - box.x0);
    pos[i * 3 + 1] = box.y0 + Math.random() * (box.y1 - box.y0);
    pos[i * 3 + 2] = box.z0 + Math.random() * (box.z1 - box.z0);
    seed[i] = Math.random();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uLightPos: { value: new THREE.Vector3() },
      uLightDir: { value: new THREE.Vector3(0, 0, -1) },
      uCos: { value: Math.cos(0.6) },
      uLevel: { value: 1 },
      uPx: { value: 1 },
      uCam: { value: new THREE.Vector3() },
    },
    vertexShader: /* glsl */`
      attribute float seed;
      uniform vec3 uLightPos; uniform vec3 uLightDir; uniform float uCos; uniform float uLevel; uniform float uPx; uniform vec3 uCam;
      varying float vI;
      void main() {
        vec3 L = position - uLightPos;
        float d = length(L);
        float c = dot(L / d, uLightDir);
        float r = acos(clamp(c, -1.0, 1.0)) / acos(uCos);
        float cone = r < 1.0 ? (0.15 + 0.85 * exp(-pow(r / 0.42, 3.0))) : 0.0;
        // Henyey–Greenstein-ish forward scattering towards the eye
        vec3 V = normalize(uCam - position);
        float g = 0.55, cosT = dot(-L / d, V);
        float hg = (1.0 - g * g) / pow(1.0 + g * g - 2.0 * g * cosT, 1.5);
        vI = uLevel * cone * hg * (0.4 + 0.6 * seed) / (d * d);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = uPx * (1.4 + 2.2 * seed) / -mv.z;
      }`,
    fragmentShader: /* glsl */`
      varying float vI;
      void main() {
        vec2 p = gl_PointCoord - 0.5;
        float a = smoothstep(0.5, 0.0, length(p));
        gl_FragColor = vec4(vec3(1.0, 0.94, 0.85) * vI * a * 0.05, 1.0);
      }`,
  });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  scene.add(pts);

  let t = 0;
  return {
    setPixelRatio(pr) { mat.uniforms.uPx.value = pr * 1.6; },
    update(dt, camera) {
      t += dt;
      const u = mat.uniforms;
      u.uLightPos.value.copy(flashlight.spot.position);
      u.uLightDir.value.copy(flashlight.dir);
      u.uCos.value = Math.cos(flashlight.spot.angle);
      u.uLevel.value = flashlight.spot.intensity / 170;
      u.uCam.value.copy(camera.position);
      // drift: a weak convection loop plus per-mote wander; settling ≈ 2 mm/s (10 µm fibres)
      for (let i = 0; i < count; i++) {
        const k = i * 3, s = seed[i];
        const x = pos[k], y = pos[k + 1], z = pos[k + 2];
        pos[k] += (0.004 * Math.sin(t * 0.21 + y * 1.3 + s * 40) + 0.002 * Math.sin(z * 0.9 + t * 0.07)) * dt;
        pos[k + 1] += (-0.002 + 0.003 * Math.sin(t * 0.17 + x * 1.1 + s * 25)) * dt;
        pos[k + 2] += 0.004 * Math.cos(t * 0.19 + x * 0.8 + s * 31) * dt;
        if (pos[k + 1] < box.y0) pos[k + 1] = box.y1;
      }
      geo.attributes.position.needsUpdate = true;
    },
  };
}
