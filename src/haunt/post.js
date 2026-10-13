// Post-processing: HDR render → beam haze → tone mapping (OutputPass) → a camera-sensor pass
// (grain that is stronger in the shadows, vignette, a little lateral chromatic aberration at the edges).

import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { createVolumetricPass } from './volumetric.js';

const SensorShader = {
  uniforms: {
    tDiffuse: { value: null },
    uTime: { value: 0 },
    uRes: { value: new THREE.Vector2(1, 1) },
    uGrain: { value: 0.07 },
    uVignette: { value: 0.55 },
    uCA: { value: 0.0018 },
    uFade: { value: 0 },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse; uniform float uTime; uniform vec2 uRes;
    uniform float uGrain; uniform float uVignette; uniform float uCA; uniform float uFade;
    varying vec2 vUv;
    float hash(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
    void main() {
      vec2 c = vUv - 0.5;
      float r2 = dot(c, c);
      // lateral chromatic aberration grows with distance from the centre
      vec2 off = c * r2 * uCA * 40.0;
      vec3 col;
      col.r = texture2D(tDiffuse, vUv - off).r;
      col.g = texture2D(tDiffuse, vUv).g;
      col.b = texture2D(tDiffuse, vUv + off).b;
      // optical vignette (cos^4-ish) — the edges of a dark frame fall into black
      float vig = pow(1.0 - clamp(r2 * 1.9, 0.0, 1.0), 1.0 + uVignette * 2.0);
      col *= mix(1.0, vig, uVignette);
      // sensor grain: per-pixel, per-frame, luminance weighted (more visible in the dark mid-tones)
      vec2 px = floor(vUv * uRes);
      float t = floor(uTime * 24.0);
      float n = hash(vec3(px, t)) + hash(vec3(px + 17.0, t + 3.0)) - 1.0;
      float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
      float w = uGrain * (0.35 + 0.65 * smoothstep(0.0, 0.25, l) * (1.0 - smoothstep(0.35, 1.0, l)));
      col += n * w * (0.12 + l);
      // dither the near-blacks so the gradient does not band in 8 bits
      col += (hash(vec3(px, t + 9.0)) - 0.5) / 255.0;
      col *= 1.0 - uFade;
      gl_FragColor = vec4(max(col, 0.0), 1.0);
    }`,
};

export function createPost(renderer, scene, camera, flashlight) {
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: 0 });
  rt.depthTexture = new THREE.DepthTexture(size.x, size.y, THREE.UnsignedIntType);
  const composer = new EffectComposer(renderer, rt);
  // the composer clones rt for its second buffer, and a cloned texture shares its GPU image: give the clone its own
  // depth texture, or the haze pass samples the depth attached to the target it draws into
  composer.renderTarget2.depthTexture = new THREE.DepthTexture(size.x, size.y, THREE.UnsignedIntType);
  composer.addPass(new RenderPass(scene, camera));
  const volume = flashlight ? createVolumetricPass(flashlight, camera) : null;
  if (volume) composer.addPass(volume);
  // (no bloom: at this exposure only the hotspot would bloom, and its blur chain was a fifth of the frame)
  const bloom = null;
  composer.addPass(new OutputPass());
  const sensor = new ShaderPass(SensorShader);
  composer.addPass(sensor);
  return {
    composer, bloom, sensor, volume,
    setSize(w, h) {
      const s = renderer.getDrawingBufferSize(new THREE.Vector2());
      // RenderTarget.setSize resizes the colour textures but not an attached depth texture
      for (const t of [composer.renderTarget1, composer.renderTarget2]) {
        if (t.depthTexture && (t.depthTexture.image.width !== s.x || t.depthTexture.image.height !== s.y)) {
          t.depthTexture.image.width = s.x; t.depthTexture.image.height = s.y;
          t.depthTexture.needsUpdate = true;
          t.width = -1;      // forces setSize below to dispose and reallocate the target
        }
      }
      composer.setSize(w, h);
      sensor.uniforms.uRes.value.set(s.x, s.y);
    },
    render(time) {
      sensor.uniforms.uTime.value = time;
      if (volume) volume.sync(time);
      composer.render();
    },
  };
}
