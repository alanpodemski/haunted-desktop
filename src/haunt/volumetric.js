// Light scattered by the dusty air inside the torch beam (single scattering, ray-marched per pixel).
// For each pixel the view ray is marched from the eye to the first surface (scene depth). At every step the
// in-scattered light is: beam intensity × cookie × shadow-map visibility / distance² × Henyey–Greenstein phase
// × the air's scattering coefficient. The march is jittered per pixel and per frame and the grain pass hides the
// noise, so 12 steps are enough.

import * as THREE from 'three';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';

const VolumetricShader = {
  uniforms: {
    tDiffuse: { value: null },
    tDepth: { value: null },
    tCookie: { value: null },
    tShadow: { value: null },
    uShadowMatrix: { value: new THREE.Matrix4() },
    uProjInv: { value: new THREE.Matrix4() },
    uCamWorld: { value: new THREE.Matrix4() },
    uCamPos: { value: new THREE.Vector3() },
    uLightPos: { value: new THREE.Vector3() },
    uLightDir: { value: new THREE.Vector3() },
    uCosOuter: { value: 0.8 },
    uIntensity: { value: 90 },
    uSigma: { value: 0.0022 },
    uG: { value: 0.45 },
    uTime: { value: 0 },
    uNear: { value: 0.05 }, uFar: { value: 40 },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */`
    #include <packing>
    uniform sampler2D tDiffuse, tDepth, tCookie, tShadow;
    uniform mat4 uShadowMatrix, uProjInv, uCamWorld;
    uniform vec3 uCamPos, uLightPos, uLightDir;
    uniform float uCosOuter, uIntensity, uSigma, uG, uTime;
    varying vec2 vUv;
    float hash(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
    vec3 worldFromDepth(vec2 uv, float d) {
      vec4 ndc = vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
      vec4 v = uProjInv * ndc; v /= v.w;
      return (uCamWorld * v).xyz;
    }
    void main() {
      vec4 base = texture2D(tDiffuse, vUv);
      float d = texture2D(tDepth, vUv).x;
      vec3 end = worldFromDepth(vUv, min(d, 0.99999));
      vec3 ro = uCamPos;
      vec3 rd = end - ro; float len = min(length(rd), 9.0); rd = normalize(rd);
      const int N = 12;
      float ds = len / float(N);
      float j = hash(gl_FragCoord.xy + fract(uTime * 7.31) * 113.0);
      float g = uG, g2 = g * g;
      vec3 acc = vec3(0.0);
      for (int i = 0; i < N; i++) {
        vec3 p = ro + rd * (float(i) + j) * ds;
        vec3 L = p - uLightPos; float dl = length(L); vec3 l = L / dl;
        float c = dot(l, uLightDir);
        if (c < uCosOuter) continue;
        vec4 sc = uShadowMatrix * vec4(p, 1.0); sc.xyz /= sc.w;
        if (sc.x < 0.0 || sc.x > 1.0 || sc.y < 0.0 || sc.y > 1.0) continue;
        vec3 cookie = texture2D(tCookie, sc.xy).rgb;
        float occ = step(sc.z - 0.002, unpackRGBAToDepth(texture2D(tShadow, sc.xy)));
        float cosT = dot(-l, -rd);        // angle between light travel and the direction back to the eye
        float hg = (1.0 - g2) / (4.0 * 3.14159 * pow(1.0 + g2 - 2.0 * g * cosT, 1.5));
        acc += cookie * occ * hg / max(dl * dl, 0.8);
      }
      vec3 inscatter = acc * ds * uSigma * uIntensity;
      gl_FragColor = vec4(base.rgb + inscatter, base.a);
    }`,
};

export function createVolumetricPass(flashlight, camera) {
  const pass = new ShaderPass(VolumetricShader);
  const u = pass.uniforms;
  u.tCookie.value = flashlight.spot.map;
  // the depth comes from whichever ping-pong target the RenderPass just drew into
  const render = pass.render.bind(pass);
  pass.render = (renderer, writeBuffer, readBuffer, dt, mask) => {
    u.tDepth.value = readBuffer.depthTexture;
    render(renderer, writeBuffer, readBuffer, dt, mask);
  };
  pass.sync = (time) => {
    const s = flashlight.spot;
    u.tShadow.value = s.shadow.map ? s.shadow.map.texture : null;
    u.uShadowMatrix.value.copy(s.shadow.matrix);
    u.uProjInv.value.copy(camera.projectionMatrixInverse);
    u.uCamWorld.value.copy(camera.matrixWorld);
    u.uCamPos.value.copy(camera.position);
    u.uLightPos.value.copy(s.position);
    u.uLightDir.value.copy(flashlight.dir);
    u.uCosOuter.value = Math.cos(s.angle);
    u.uIntensity.value = s.intensity;
    u.uTime.value = time;
    pass.enabled = s.intensity > 0.5 && !!u.tShadow.value;
  };
  return pass;
}
