// The live wallpaper: renderer, fixed camera, the room, the torch, the dust, the physics (file boxes), the camera
// flash and the creature.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { CAMERA } from './layout.js';
import { loadRoom } from './room.js';
import { createFlashlight } from './flashlight.js';
import { createDust } from './dust.js';
import { createPost } from './post.js';
import { createCreature } from './creature.js';
import { createPhysics } from './physics.js';
import { createBoxes } from './boxes.js';
import { createPhoto } from './photo.js';
import { createItems } from './items.js';

export async function createHaunt(canvas, { sound, desk, quality = 1 } = {}) {
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

  // ---- the house's own geometry: doors and windows, from the environment's empties
  const nav = { doors: [], end: new THREE.Vector3(0, 0, -14) };
  const windows = [];
  room.root.updateMatrixWorld(true);
  room.root.traverse((o) => {
    const m = o.name.match(/^Door_([LR]\d)$/);
    if (m) {
      const inside = room.root.getObjectByName(`Inside_${m[1]}`);
      nav.doors.push({
        id: m[1], side: m[1][0],
        door: o.getWorldPosition(new THREE.Vector3()),
        into: o.getWorldDirection(new THREE.Vector3()).setY(0).normalize(),     // local +Z: into the hallway
        inside: inside ? inside.getWorldPosition(new THREE.Vector3()) : o.getWorldPosition(new THREE.Vector3()),
      });
    }
    if (/^Window_(L\d|R\d|End)$/.test(o.name)) {
      windows.push({ id: o.name, pos: o.getWorldPosition(new THREE.Vector3()), out: o.getWorldDirection(new THREE.Vector3()).negate() });
      if (o.name === 'Window_End') nav.end.copy(o.getWorldPosition(new THREE.Vector3())).setY(0);
    }
  });
  nav.doors.sort((a, b) => b.door.z - a.door.z);

  // Moonlight is baked (blender/bake_moon.py): irradiance from a low moon behind every window, through the windows
  // and out of the doorways, on the same UV1 atlas as the ambient occlusion. It costs nothing per frame; lightning
  // just turns it up for an instant.
  const MOON = 3.6;               // π × the bake's scale (see bake_moon.py)
  const moonMats = [];
  try {
    const moonTex = await new THREE.TextureLoader().loadAsync('/models/hallway_moon.jpg');
    moonTex.colorSpace = THREE.SRGBColorSpace; moonTex.flipY = false; moonTex.channel = 1;
    moonTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    room.root.traverse((o) => {
      if (!o.isMesh) return;
      for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
        if (!m.aoMap || moonMats.includes(m)) continue;
        m.lightMap = moonTex; m.lightMapIntensity = MOON; m.needsUpdate = true;
        moonMats.push(m);
      }
    });
  } catch (err) { console.warn('[haunt] no baked moonlight:', err && err.message); }
  const moons = [];
  let moonTurn = 0, frameNo = 0;
  const outside = [];
  room.root.traverse((o) => { if (o.isMesh && /outside/i.test(o.name + (o.material && o.material.name))) outside.push(o.material); });

  // Lightning: now and then the sky behind the windows flashes two or three times; the thunder follows a second or
  // three later (the storm is a few hundred metres to a kilometre off). For that instant the whole hallway shows.
  let nextLightning = performance.now() / 1000 + 25 + Math.random() * 20, strike = null;
  function lightning(dt) {
    const now = performance.now() / 1000;
    if (!strike && now >= nextLightning) {
      const pulses = [[0, 0.07, 1], [0.16, 0.05, 0.6], [0.4, 0.12, 0.85]].slice(0, 2 + (Math.random() < 0.6 ? 1 : 0));
      strike = { t: 0, pulses, unstage: creature.stageForLightning() };
      nextLightning = now + 20 + Math.random() * 35;
      if (sound) setTimeout(() => sound.thunder(0.6 + Math.random() * 0.4), 1000 + Math.random() * 2000);
    }
    let k = 0;
    if (strike) {
      strike.t += dt;
      for (const [t0, len, a] of strike.pulses) if (strike.t >= t0 && strike.t < t0 + len) k = Math.max(k, a);
      if (strike.t > 0.7) { if (strike.unstage) strike.unstage(); strike = null; }
    }
    for (const m of moonMats) m.lightMapIntensity = MOON * (1 + 40 * k);
    for (const m of outside) m.emissiveIntensity = 1 + 8 * k;
  }

  const flashlight = createFlashlight(scene, camera, { candela: 170 });   // a 14 m hallway needs a stronger torch than the room did
  flashlight.aimAt(room.defaultTarget);
  const dust = createDust(scene, flashlight);
  dust.setPixelRatio(renderer.getPixelRatio());
  const post = createPost(renderer, scene, camera, flashlight);

  const physics = await createPhysics(room.root);
  physics.world.step();                                  // build the query structures before the first ray
  flashlight.setCaster((o, d) => physics.cast(o, d));
  const boxes = createBoxes({ scene, physics, camera, desk, sound });

  // camera shake (the jumpscare): a decaying random rotation around the fixed view
  const baseQuat = camera.quaternion.clone();
  let shake = 0;
  const creature = await createCreature(scene, loader, {
    flashlight, camera, sound, physics, boxes, nav,
    onJumpscare() {
      shake = 1;
      boxes.blast(camera.position, 60, 4);
      desk.scatter(innerWidth / 2, innerHeight * 0.45, 1.2);
    },
    onBlackout(on) { post.sensor.uniforms.uFade.value = on ? 1 : 0; },
    onScare() { shake = 0.7; },
    onCross() { nextLightning = 0; },      // lightning as it runs across
    // a file it carried off comes back to the desktop, renamed
    onReturn(id) {
      const icon = desk.getIcon(id);
      if (!icon) return;
      const m = icon.name.match(/^(.*?)(\.[^.]+)?$/);
      const tag = /candy/i.test(icon.name) ? ' (eaten)' : ' (chewed)';
      desk.returnIcon(id);
      if (!icon.name.includes(tag)) desk.renameIcon(id, m[1] + tag + (m[2] || ''));
    },
  });
  const photo = createPhoto({ renderer, scene, camera, post, creature, desk, sound });
  const items = createItems({ scene, physics, boxes, flashlight, sound, desk });
  creature.setItems(items);
  items.warm(renderer, camera);

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
  const isMoving = () => {
    if (boxes.holding) return true;
    for (const b of boxes.boxes.values()) if (!b.body.isSleeping()) return true;
    return items.live.length > 0;
  };
  function frame(now) {
    requestAnimationFrame(frame);
    const active = now - lastInput < 1500 || creature.busy || shake > 0 || isMoving();
    if (now - last < 15) return;      // a steady 60 fps (switching to 30 when idle read as stutter)
    void active;
    let dt = (now - last) / 1000; last = now;
    if (!(dt > 0)) dt = 1 / 60;
    dt = Math.min(dt, 1 / 20);
    if (paused) return;
    simulate(dt);
    const q = gpuBegin();
    photo.render(time);
    gpuEnd(q);
  }
  requestAnimationFrame(frame);

  /** one frame of the world without drawing (scripted tests drive it through advance()) */
  function simulate(dt) {
    time += dt;
    flashlight.update(dt);
    creature.update(dt);
    physics.step(dt, (h) => { boxes.beforeStep(h); creature.beforeStep(h); });
    creature.afterStep();
    boxes.sync(dt);
    // doors that are pushed swing and creak (rusted hinges: stick-slip, louder the faster)
    for (const { d, w, pos } of physics.syncDoors()) {
      if (w > 0.35 && sound && (!d.lastCreak || time - d.lastCreak > 0.45)) { d.lastCreak = time; sound.doorCreak(pos, Math.min(1, w / 2)); }
    }
    items.update(dt, time);
    lightning(dt);
    if (shake > 0) {
      shake = Math.max(0, shake - dt * 1.4);
      const a = 0.035 * shake * shake;
      camera.quaternion.copy(baseQuat).multiply(new THREE.Quaternion().setFromEuler(
        new THREE.Euler((Math.random() - 0.5) * a, (Math.random() - 0.5) * a, (Math.random() - 0.5) * a * 0.5)));
      if (shake === 0) camera.quaternion.copy(baseQuat);
      camera.updateMatrixWorld();
    }
    dust.update(dt, camera);
    if (sound) sound.setListener(camera);
    batteryShown -= dt;
    if (batteryShown <= 0) { batteryShown = 1; desk.setBattery(flashlight.battery.charge * 100); }
  }
  let batteryShown = 0;

  return {
    renderer, scene, camera, flashlight, creature, room, post, moons, nav, physics, boxes, photo, items,
    get renderScale() { return renderScale; },
    /** lightning now (L key, for recording) */
    strike() { nextLightning = 0; },
    setPointer(clientX, clientY) {
      flashlight.setPointer((clientX / innerWidth) * 2 - 1, -(clientY / innerHeight) * 2 + 1);
    },
    pause(v = !paused) { paused = v; return paused; },
    /** run the world forward by `seconds` at 60 Hz (for tests and recordings), then draw one frame */
    advance(seconds) { for (let t = 0; t < seconds; t += 1 / 60) simulate(1 / 60); photo.render(time); },
  };
}
