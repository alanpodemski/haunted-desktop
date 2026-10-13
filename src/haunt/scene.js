// The live wallpaper: renderer, fixed camera, the room, the torch, the dust and the creature.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { CAMERA, CORRIDOR, CORRIDOR_LANE_Z } from './layout.js';
import { loadRoom } from './room.js';
import { createFlashlight } from './flashlight.js';
import { createDust } from './dust.js';
import { createPost } from './post.js';
import { createCreature } from './creature.js';

export async function createHaunt(canvas, { sound, quality = 1 } = {}) {
  // Render at CSS-pixel resolution (1×) by default: the scene is dark and grainy, so 2× Retina pixels are
  // invisible here but cost 4× the GPU work. ?hq goes back to the full device resolution.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
  const maxDpr = () => Math.min(window.devicePixelRatio || 1, quality >= 2 ? 2 : quality >= 1 ? 1 : 0.75);
  // dynamic resolution: the render scale drops (down to 0.65) when the GPU takes longer than ~7 ms per frame,
  // so a big screen stays at 60 fps and the fans stay off; the DOM desktop on top stays sharp either way
  let renderScale = 1;
  const dpr = () => maxDpr() * renderScale;
  renderer.setPixelRatio(dpr());
  renderer.setSize(innerWidth, innerHeight, false);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const camera = new THREE.PerspectiveCamera(CAMERA.fov, innerWidth / innerHeight, 0.05, 40);
  camera.position.set(...CAMERA.pos);
  camera.lookAt(...CAMERA.look);
  camera.updateMatrixWorld();

  const draco = new DRACOLoader().setDecoderPath('/draco/');
  const loader = new GLTFLoader().setDRACOLoader(draco);

  const room = await loadRoom(loader, renderer);
  scene.add(room.root);

  // Total darkness in the room, except for what leaks down the corridor from a window somewhere to the right:
  // a cold, very weak light that only makes the doorway a slightly-less-black shape.
  const leak = new THREE.SpotLight(0x8ea4cc, 1.6, 0, 0.75, 0.9, 2);
  leak.position.set(CORRIDOR.x1 - 0.15, 2.1, CORRIDOR_LANE_Z - 0.2);
  leak.target.position.set(CORRIDOR.x0, 0.4, CORRIDOR_LANE_Z + 0.2);
  leak.castShadow = true;
  leak.shadow.mapSize.set(512, 512);
  leak.shadow.bias = -0.0002; leak.shadow.normalBias = 0.02;
  leak.shadow.camera.near = 0.1; leak.shadow.camera.far = 10;
  // the corridor light never moves: its shadow map is only redrawn while the creature is out
  leak.shadow.autoUpdate = false;
  leak.shadow.needsUpdate = true;
  scene.add(leak, leak.target);
  const fill = new THREE.HemisphereLight(0x202838, 0x0a0806, 0.004);
  scene.add(fill);

  const flashlight = createFlashlight(scene, camera);
  flashlight.aimAt(room.defaultTarget);
  const dust = createDust(scene, flashlight);
  dust.setPixelRatio(renderer.getPixelRatio());
  const post = createPost(renderer, scene, camera, flashlight);

  const creature = await createCreature(scene, loader, { flashlight, camera, sound });

  function resize() {
    renderer.setPixelRatio(dpr());
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    // keep the doorway framed on tall or narrow windows: widen the vertical FOV when the frame is narrower than 16:10
    camera.fov = CAMERA.fov * Math.max(1, (1.6 / camera.aspect) ** 0.6);
    camera.updateProjectionMatrix();
    post.setSize(innerWidth, innerHeight);
    dust.setPixelRatio(renderer.getPixelRatio());
  }
  addEventListener('resize', resize);
  resize();

  // Frame pacing: 60 fps while something moves on screen (the mouse moved recently, or the creature is out),
  // 30 fps when only the hand tremor and the dust are moving. 120 Hz screens never render at 120.
  const gl = renderer.getContext();
  const timer = gl.getExtension('EXT_disjoint_timer_query_webgl2');
  const queries = [];
  let gpuSum = 0, gpuN = 0;
  function gpuBegin() {
    if (!timer || queries.length > 4) return null;
    const q = gl.createQuery(); gl.beginQuery(timer.TIME_ELAPSED_EXT, q); return q;
  }
  function gpuEnd(q) {
    if (q) { gl.endQuery(timer.TIME_ELAPSED_EXT); queries.push(q); }
    while (queries.length && gl.getQueryParameter(queries[0], gl.QUERY_RESULT_AVAILABLE)) {
      const r = queries.shift();
      if (!gl.getParameter(timer.GPU_DISJOINT_EXT)) { gpuSum += gl.getQueryParameter(r, gl.QUERY_RESULT) / 1e6; gpuN++; }
      gl.deleteQuery(r);
    }
    if (gpuN >= 30 && quality < 2) {
      const ms = gpuSum / gpuN; gpuSum = 0; gpuN = 0;
      const next = THREE.MathUtils.clamp(renderScale * Math.sqrt(7 / ms), 0.65, 1);
      if (Math.abs(next - renderScale) > 0.08) { renderScale = next; resize(); }
    }
  }

  let last = performance.now(), time = 0, paused = false, lastInput = -1e9;
  addEventListener('pointermove', () => { lastInput = performance.now(); }, { passive: true });
  function frame(now) {
    requestAnimationFrame(frame);
    const active = now - lastInput < 1500 || creature.busy;
    const minMs = active ? 15 : 31;
    if (now - last < minMs) return;
    let dt = (now - last) / 1000; last = now;
    if (!(dt > 0)) dt = 1 / 60;
    dt = Math.min(dt, 1 / 20);
    if (paused) return;
    time += dt;
    flashlight.update(dt);
    creature.update(dt);
    if (creature.busy || creature.actor.root.visible) leak.shadow.needsUpdate = true;
    dust.update(dt, camera);
    if (sound) sound.setListener(camera);
    const q = gpuBegin();
    post.render(time);
    gpuEnd(q);
  }
  requestAnimationFrame(frame);

  return {
    renderer, scene, camera, flashlight, creature, room, post, leak,
    get renderScale() { return renderScale; },
    setPointer(clientX, clientY) {
      flashlight.setPointer((clientX / innerWidth) * 2 - 1, -(clientY / innerHeight) * 2 + 1);
    },
    pause(v = !paused) { paused = v; return paused; },
  };
}
