// The thing in the corridor. public/models/creature.glb (blender/creature.py) with in-place clips run / crawl /
// idle / peek / flee and public/models/creature.json with the ground speed of each cycle. Without the glb a crude
// stand-in is used so the scheduling can be tested.
//
// Every so often one event plays: it dashes past the doorway, scuttles past on all fours, peeks around the jamb,
// stands in the doorway in the dark until the beam finds it and then bolts, or (rarely) runs into the room.
// Events are coroutines (generators): each `yield` waits one frame and receives dt.

import * as THREE from 'three';
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js';
import { ROOM, DOOR, CORRIDOR, CORRIDOR_LANE_Z } from './layout.js';

const DEFAULT_META = {
  run: { speed: 5.6, duration: 0.62 },
  crawl: { speed: 3.0, duration: 0.5 },
  walk: { speed: 0.35, duration: 4 },
  drag: { speed: 0.43, duration: 5 },
  scream: { duration: 2.8 },
  idle: { duration: 4 },
  peek: { duration: 4.2 },
  flee: { duration: 0.9 },
};

// ----------------------------------------------------------------------------------------- the actor
async function loadActor(loader) {
  let gltf = null, meta = {};
  try { gltf = await loader.loadAsync('/models/creature.glb'); }
  catch (err) { console.warn('[haunt] creature.glb missing, using the stand-in:', err && err.message); }
  try { const r = await fetch('/models/creature.json'); if (r.ok) meta = await r.json(); } catch {}
  for (const k of Object.keys(DEFAULT_META)) meta[k] = { ...DEFAULT_META[k], ...(meta[k] || {}) };
  return gltf ? gltfActor(gltf, meta) : standInActor(meta);
}

function gltfActor(gltf, meta) {
  const root = new THREE.Group();
  const model = SkeletonUtils.clone(gltf.scene);
  root.add(model);
  const eyeMats = [];
  let head = null;
  model.traverse((o) => {
    if (o.isBone && !head && /head/i.test(o.name)) head = o;
    if (!o.isMesh) return;
    o.castShadow = true; o.receiveShadow = true;
    o.frustumCulled = false;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (/eye/i.test(m.name)) {
        // the tapetum: a retro-reflector that sends the torch straight back at you
        m.emissive = new THREE.Color(0xfff2c8);
        m.emissiveIntensity = 0;
        eyeMats.push(m);
      }
    }
  });
  const mixer = new THREE.AnimationMixer(model);
  const actions = {};
  for (const clip of gltf.animations) {
    const a = mixer.clipAction(clip);
    actions[clip.name] = a;
    if (meta[clip.name]) meta[clip.name].duration = clip.duration;
  }
  let current = null;
  return {
    root, meta, head,
    has: (name) => !!actions[name],
    play(name, { loop = true, fade = 0.15, timeScale = 1 } = {}) {
      const a = actions[name]; if (!a) return 0;
      a.reset();
      a.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
      a.clampWhenFinished = !loop;
      a.timeScale = timeScale;
      a.enabled = true;
      if (current && current !== a && fade > 0) a.crossFadeFrom(current, fade, false);
      else if (current && current !== a) current.stop();
      a.play();
      current = a;
      return a.getClip().duration;
    },
    get time() { return current ? current.time : 0; },
    get clip() { return current ? current.getClip().name : null; },
    setTimeScale(s) { if (current) current.timeScale = s; },
    setEyeGlow(v) { for (const m of eyeMats) m.emissiveIntensity = v; },
    headPos(out) { return head ? head.getWorldPosition(out) : out.set(root.position.x, 1.8, root.position.z); },
    update(dt) { mixer.update(dt); },
  };
}

/** a capsule figure with procedural motion, just enough to judge timing and framing */
function standInActor(meta) {
  const root = new THREE.Group();
  const skin = new THREE.MeshStandardMaterial({ color: 0xb8b4ac, roughness: 0.45 });
  const eyeMat = new THREE.MeshStandardMaterial({ name: 'Eyes', color: 0x111111, emissive: 0xfff2c8, emissiveIntensity: 0 });
  const body = new THREE.Group(); root.add(body);
  const cap = (r, l, x, y, z) => { const m = new THREE.Mesh(new THREE.CapsuleGeometry(r, l, 4, 8), skin); m.position.set(x, y, z); m.castShadow = true; body.add(m); return m; };
  const torso = cap(0.13, 0.55, 0, 1.3, 0);
  const headM = cap(0.1, 0.1, 0, 1.78, 0.04);
  const eyes = [-0.035, 0.035].map((x) => { const e = new THREE.Mesh(new THREE.SphereGeometry(0.012, 8, 6), eyeMat); e.position.set(x, 1.8, 0.13); body.add(e); return e; });
  const limb = (x, y) => { const g = new THREE.Group(); g.position.set(x, y, 0); body.add(g); const m = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.8, 4, 8), skin); m.position.y = -0.45; m.castShadow = true; g.add(m); return g; };
  const armL = limb(-0.2, 1.55), armR = limb(0.2, 1.55), legL = limb(-0.1, 0.95), legR = limb(0.1, 0.95);
  let name = 'idle', t = 0, ts = 1;
  return {
    root, meta, head: headM,
    has: () => true,
    play(n, { timeScale = 1 } = {}) { name = n; t = 0; ts = timeScale; return meta[n] ? meta[n].duration : 1; },
    get time() { return t; },
    get clip() { return name; },
    setTimeScale(s) { ts = s; },
    setEyeGlow(v) { eyeMat.emissiveIntensity = v; },
    headPos(out) { return headM.getWorldPosition(out); },
    update(dt) {
      t += dt * ts;
      const w = name === 'run' ? Math.PI * 2 / meta.run.duration : name === 'crawl' ? Math.PI * 2 / meta.crawl.duration : 1.2;
      const s = Math.sin(t * w);
      const amp = name === 'run' ? 0.9 : name === 'crawl' ? 0.6 : 0.03;
      legL.rotation.x = s * amp; legR.rotation.x = -s * amp; armL.rotation.x = -s * amp; armR.rotation.x = s * amp;
      body.rotation.x = name === 'run' ? 0.35 : name === 'crawl' ? 1.25 : 0.12;
      body.position.y = name === 'crawl' ? -0.9 : Math.abs(s) * (name === 'run' ? 0.06 : 0.005);
      body.position.x = name === 'peek' ? 0.35 * Math.sin(Math.min(1, t / (meta.peek.duration)) * Math.PI) : 0;
      void torso; void eyes;
    },
  };
}

// ----------------------------------------------------------------------------------------- geometry helpers
const DOOR_X0 = DOOR.cx - DOOR.w / 2, DOOR_X1 = DOOR.cx + DOOR.w / 2;
const v3 = () => new THREE.Vector3();

/** is the straight line from a (in the room) to b visible, i.e. not blocked by the back wall? */
function seenThroughDoor(a, b) {
  if (b.z > ROOM.z0) return true;
  const t = (ROOM.z0 - a.z) / (b.z - a.z);
  const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t;
  return x > DOOR_X0 + 0.02 && x < DOOR_X1 - 0.02 && y < DOOR.h - 0.02;
}

const rand = (a, b) => a + Math.random() * (b - a);
const pick = (weights) => {
  let s = 0; for (const k in weights) s += weights[k];
  let r = Math.random() * s;
  for (const k in weights) { r -= weights[k]; if (r <= 0) return k; }
  return Object.keys(weights)[0];
};

// ----------------------------------------------------------------------------------------- controller
export async function createCreature(scene, loader, { flashlight, camera, sound, onEvent } = {}) {
  const actor = await loadActor(loader);
  const { root, meta } = actor;
  root.visible = false;
  scene.add(root);

  let job = null, jobName = null;
  let nextAt = performance.now() / 1000 + rand(6, 9);
  let last = null, lastRoomRun = -1e9, count = 0;
  const tmp = v3(), head = v3(), chest = v3();

  const faceAngle = (dx, dz) => Math.atan2(dx, dz);   // model faces +Z
  const place = (x, z, yaw) => { root.position.set(x, 0, z); root.rotation.set(0, yaw, 0); root.visible = true; };

  /** how strongly the beam is on the creature right now (0..1), counting only what the camera can see */
  function litness() {
    if (!root.visible) return 0;
    actor.headPos(head);
    chest.set(root.position.x, 1.25, root.position.z);
    let best = 0;
    for (const p of [head, chest]) {
      if (!seenThroughDoor(flashlight.pos, p) || !seenThroughDoor(camera.position, p)) continue;
      best = Math.max(best, flashlight.exposure(p));
    }
    return best;
  }

  // footfalls from the gait phase: two per cycle for the biped, four for the crawl
  let lastPhase = 0;
  function footsteps(speedScale = 1) {
    const clip = actor.clip;
    if (!['run', 'crawl', 'flee', 'walk', 'drag'].includes(clip)) return;
    const dur = (meta[clip] && meta[clip].duration) || 0.6;
    // footfalls per clip: run 2 per cycle, crawl 4; the long walk and drag clips hold several slow steps
    const per = { run: 2, flee: 2, crawl: 4, walk: 8, drag: 6 }[clip];
    const ph = ((actor.time / dur) * per) % 1;
    if (ph < lastPhase) {
      tmp.copy(root.position);
      const occluded = !seenThroughDoor(camera.position, tmp.set(tmp.x, 0.3, tmp.z));
      const kind = clip === 'crawl' || clip === 'drag' ? 'crawl' : 'run';
      const soft = clip === 'walk' ? 0.55 : clip === 'drag' ? 0.8 : 1;
      sound && sound.footstep({ pos: root.position.clone(), kind, occluded, gain: speedScale * soft });
    }
    lastPhase = ph;
  }

  // ---- coroutine helpers
  function* wait(sec) { let t = 0; while (t < sec) t += yield; }

  /** run along a polyline at the clip's matching speed, turning to face where it goes */
  function* travel(points, clip, { speed = meta[clip].speed, accel = 14, startSpeed = speed, turnRate = 9 } = {}) {
    let v = startSpeed;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      const dx = b[0] - a[0], dz = b[1] - a[1];
      const len = Math.hypot(dx, dz);
      let s = 0;
      const want = faceAngle(dx, dz);
      while (s < len) {
        const dt = yield;
        v = Math.min(speed, v + accel * dt);
        s = Math.min(len, s + v * dt);
        root.position.x = a[0] + dx * s / len;
        root.position.z = a[1] + dz * s / len;
        let d = want - root.rotation.y; d = Math.atan2(Math.sin(d), Math.cos(d));
        root.rotation.y += d * Math.min(1, turnRate * dt);
        actor.setTimeScale(v / meta[clip].speed);      // the gait follows the ground speed, so feet do not skate
        footsteps(v / meta[clip].speed);
      }
    }
  }

  /** caught in the light: it turns to you and screams, then runs */
  function* screamAtYou() {
    sound && sound.sting(1);
    flashlight.stutter(0.6);
    if (!actor.has('scream')) return;
    const want = faceAngle(camera.position.x - root.position.x, camera.position.z - root.position.z);
    actor.play('scream', { loop: false, fade: 0.12, timeScale: 1.25 });
    let t = 0;
    while (t < 1.25) {
      const dt = yield; t += dt;
      let d = want - root.rotation.y; d = Math.atan2(Math.sin(d), Math.cos(d));
      root.rotation.y += d * Math.min(1, 10 * dt);
      actor.setEyeGlow(eyeGlow());
    }
  }

  /** walk or drag along the corridor lane past the doorway; if the beam catches it, it screams and runs */
  function* slowPass(clip) {
    const dir = Math.random() < 0.5 ? 1 : -1;
    const span = clip === 'walk' ? 1.7 : 1.3;
    const x0 = DOOR.cx - dir * span, x1 = DOOR.cx + dir * (span + 0.6);
    const z = CORRIDOR_LANE_Z + rand(-0.05, 0.2);
    place(x0, z, faceAngle(dir, 0));
    actor.play(clip, { fade: 0 });
    const v = meta[clip].speed;
    let seen = 0;
    while (dir > 0 ? root.position.x < x1 : root.position.x > x1) {
      const dt = yield;
      root.position.x += dir * v * dt;
      footsteps();
      seen = litness() > 0.2 ? seen + dt : Math.max(0, seen - dt);
      if (seen > 0.35) {
        yield* screamAtYou();
        actor.play('run', { fade: 0.15 });
        const xe = dir > 0 ? CORRIDOR.x1 - 0.4 : CORRIDOR.x0 + 0.4;
        yield* travel([[root.position.x, root.position.z], [root.position.x + dir * 0.4, CORRIDOR_LANE_Z], [xe, CORRIDOR_LANE_Z]], 'run', { startSpeed: 1, accel: 10 });
        return;
      }
    }
  }

  // ---- events
  const EVENTS = {
    /** shuffles past the doorway, slowly */
    *walk() { yield* slowPass(actor.has('walk') ? 'walk' : 'run'); },
    /** drags itself across the corridor floor */
    *drag() { yield* slowPass(actor.has('drag') ? 'drag' : 'crawl'); },
    /** sprint past the doorway */
    *dash() {
      const dir = Math.random() < 0.5 ? 1 : -1;
      const x0 = dir > 0 ? CORRIDOR.x0 + 0.5 : CORRIDOR.x1 - 0.5, x1 = dir > 0 ? CORRIDOR.x1 - 0.4 : CORRIDOR.x0 + 0.4;
      const z = CORRIDOR_LANE_Z + rand(-0.15, 0.2);
      place(x0, z, faceAngle(dir, 0));
      actor.play('run', { fade: 0 });
      yield* travel([[x0, z], [x1, z]], 'run', { startSpeed: meta.run.speed * 0.8 });
    },
    /** on all fours, fast and low */
    *crawl() {
      const dir = Math.random() < 0.5 ? 1 : -1;
      const x0 = dir > 0 ? CORRIDOR.x0 + 0.5 : CORRIDOR.x1 - 0.5, x1 = dir > 0 ? CORRIDOR.x1 - 0.4 : CORRIDOR.x0 + 0.4;
      const z = CORRIDOR_LANE_Z + rand(-0.1, 0.25);
      place(x0, z, faceAngle(dir, 0));
      actor.play(actor.has('crawl') ? 'crawl' : 'run', { fade: 0 });
      const clip = actor.has('crawl') ? 'crawl' : 'run';
      yield* travel([[x0, z], [x1, z]], clip);
    },
    /** leans out from behind the left jamb, stares, pulls back (faster if the beam catches it) */
    *peek() {
      if (!actor.has('peek')) return yield* EVENTS.watch();
      place(DOOR_X0 - 0.32, ROOM.z0 - 0.42, faceAngle(camera.position.x - DOOR_X0, camera.position.z - ROOM.z0) * 0.5);
      const dur = actor.play('peek', { loop: false, fade: 0 });
      let t = 0, caught = false;
      while (t < dur) {
        const dt = yield;
        t += dt * (caught ? 3 : 1);
        if (!caught && litness() > 0.25) { caught = true; actor.setTimeScale(3); sound && sound.sting(0.5); flashlight.stutter(0.35); }
        actor.setEyeGlow(eyeGlow());
      }
      // you hear it leave
      root.visible = false;
      yield* wait(0.25);
      for (let i = 0; i < 6; i++) { sound && sound.footstep({ pos: new THREE.Vector3(DOOR_X0 - 1 - i * 0.6, 0, CORRIDOR_LANE_Z), kind: 'run', occluded: true, gain: 0.8 }); yield* wait(0.16); }
    },
    /** stands just inside the doorway in the dark; bolts when the beam lands on it */
    *watch() {
      const x = DOOR.cx + rand(-0.12, 0.12), z = ROOM.z0 - rand(0.35, 0.7);
      place(x, z, faceAngle(camera.position.x - x, camera.position.z - z));
      actor.play('idle', { fade: 0 });
      let seen = 0, t = 0;
      const patience = rand(9, 16);
      while (t < patience) {
        const dt = yield; t += dt;
        const l = litness();
        actor.setEyeGlow(eyeGlow());
        seen = l > 0.2 ? seen + dt : Math.max(0, seen - dt * 0.5);
        if (seen > 0.14) break;
      }
      const caught = seen > 0.14;
      if (caught) yield* screamAtYou();
      // the turn and the first strides
      const dir = Math.random() < 0.5 ? 1 : -1;
      if (actor.has('flee') && dir > 0) {
        const dur = actor.play('flee', { loop: false, fade: 0.08, timeScale: caught ? 1.15 : 0.9 });
        let ft = 0; const x0 = root.position.x;
        const yaw0 = root.rotation.y;
        while (ft < dur) {
          const dt = yield; ft += dt * (caught ? 1.15 : 0.9);
          // it starts moving in the last part of the clip, accelerating towards run speed
          const u = THREE.MathUtils.smoothstep(ft / dur, 0.45, 1);
          root.position.x = x0 + 0.5 * meta.run.speed * u * u * dur * 0.55;
          root.rotation.y = yaw0 * (1 - u);
          footsteps();
        }
        root.rotation.y = faceAngle(1, 0);
        actor.play('run', { fade: 0 });
        yield* travel([[root.position.x, root.position.z], [root.position.x + 0.6, CORRIDOR_LANE_Z], [CORRIDOR.x1 - 0.4, CORRIDOR_LANE_Z]], 'run', { startSpeed: meta.run.speed * 0.7 });
      } else {
        actor.play('run', { fade: 0.12 });
        yield* travel([[root.position.x, root.position.z], [root.position.x + dir * 0.5, CORRIDOR_LANE_Z], [dir > 0 ? CORRIDOR.x1 - 0.4 : CORRIDOR.x0 + 0.4, CORRIDOR_LANE_Z]], 'run', { startSpeed: 1.5, accel: 18 });
      }
    },
    /** rare: comes through the doorway and runs past you, out of view to the left */
    *intrude() {
      const x0 = CORRIDOR.x0 + 0.6;
      place(x0, CORRIDOR_LANE_Z, faceAngle(1, 0));
      actor.play('run', { fade: 0 });
      flashlight.stutter(1.2);
      yield* travel([
        [x0, CORRIDOR_LANE_Z], [DOOR.cx - 0.5, CORRIDOR_LANE_Z], [DOOR.cx, ROOM.z0 - 0.2],
        [DOOR.cx - 0.25, ROOM.z0 + 1.6], [ROOM.x0 + 0.7, -0.4], [ROOM.x0 + 0.5, 0.6],
      ], 'run', { startSpeed: meta.run.speed * 0.8, turnRate: 7 });
      sound && sound.sting(0.7);
    },
  };

  function eyeGlow() {
    // retro-reflection: bright only when the torch is close to the line of sight and pointed at the face
    actor.headPos(head);
    if (!seenThroughDoor(flashlight.pos, head)) return 0;
    const e = flashlight.exposure(head);
    tmp.copy(camera.position).sub(head).normalize();
    const facing = Math.max(0, Math.sin(root.rotation.y) * tmp.x + Math.cos(root.rotation.y) * tmp.z);
    return e * Math.pow(facing, 4) * 40;
  }

  function start(name) {
    if (!EVENTS[name]) return false;
    job = EVENTS[name](); jobName = name;
    job.next();      // run to the first yield
    count++; last = name;
    if (name === 'intrude') lastRoomRun = performance.now() / 1000;
    onEvent && onEvent(name);
    return true;
  }

  function schedule() {
    const now = performance.now() / 1000;
    const w = { dash: 26, crawl: 14, walk: 16, drag: 10, peek: 12, watch: 18, intrude: 6 };
    if (!actor.has('peek')) delete w.peek;
    if (count < 1) { start('dash'); return; }
    if (count < 3 || now - lastRoomRun < 90) delete w.intrude;
    if (last && w[last] && last !== 'dash') w[last] *= 0.3;
    start(pick(w));
  }

  return {
    actor,
    get busy() { return !!job; },
    get event() { return jobName; },
    trigger(name) { if (job) return false; return start(name); },
    update(dt) {
      actor.update(dt);
      const now = performance.now() / 1000;
      if (!job && now >= nextAt) schedule();
      if (job) {
        const r = job.next(dt);
        if (r.done) {
          job = null; jobName = null; root.visible = false; actor.setEyeGlow(0);
          nextAt = now + rand(14, 38);
        }
      }
    },
  };
}
