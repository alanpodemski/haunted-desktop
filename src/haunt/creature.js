// The thing in the corridor. public/models/creature.glb (blender/creature.py) with in-place clips run / crawl /
// idle / peek / flee and public/models/creature.json with the ground speed of each cycle. Without the glb a crude
// stand-in is used so the scheduling can be tested.
//
// Every so often one event plays: it dashes past the doorway, scuttles past on all fours, peeks around the jamb,
// stands in the doorway in the dark until the beam finds it and then bolts, or (rarely) runs into the room.
// Events are coroutines (generators): each `yield` waits one frame and receives dt.

import * as THREE from 'three';
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js';
import { HALL } from './layout.js';

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
  const actor = gltf ? gltfActor(gltf, meta) : standInActor(meta);
  // a second copy for photographs, so posing it for a picture never interferes with whatever the real one does
  actor.another = () => (gltf ? gltfActor(gltf, meta) : standInActor(meta));
  return actor;
}

function gltfActor(gltf, meta) {
  const root = new THREE.Group();
  const model = SkeletonUtils.clone(gltf.scene);
  root.add(model);
  const eyeMats = [];
  let head = null, handR = null, handL = null;
  const feet = [];
  model.traverse((o) => {
    if (o.isBone && /(left|right)(toebase|foot)$/i.test(o.name) && !/toe_end/i.test(o.name)) feet.push(o);
    if (o.isBone && !head && /head/i.test(o.name)) head = o;
    if (o.isBone && !handR && /righthand$/i.test(o.name)) handR = o;
    if (o.isBone && !handL && /lefthand$/i.test(o.name)) handL = o;
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
    /** between its hands: where something carried in both arms sits */
    carryPos(out) {
      if (handR && handL) {
        const a = handR.getWorldPosition(new THREE.Vector3()), b = handL.getWorldPosition(new THREE.Vector3());
        return out.copy(a).add(b).multiplyScalar(0.5);
      }
      return out.set(root.position.x, 1.0, root.position.z);
    },
    /** world positions of what touches the floor: toes (or feet), and the hands when it is on all fours */
    contactPoints() {
      const out = [];
      const toes = feet.filter((b) => /toebase/i.test(b.name));
      for (const b of (toes.length ? toes : feet)) out.push([b.name, b.getWorldPosition(new THREE.Vector3())]);
      if ((current && /crawl|drag/.test(current.getClip().name)) && handL && handR) {
        out.push(['handL', handL.getWorldPosition(new THREE.Vector3())], ['handR', handR.getWorldPosition(new THREE.Vector3())]);
      }
      return out;
    },
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
    contactPoints() { return []; },
    carryPos(out) { return out.set(root.position.x, 1.0, root.position.z).addScaledVector(new THREE.Vector3(Math.sin(root.rotation.y), 0, Math.cos(root.rotation.y)), 0.35); },
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
const v3 = () => new THREE.Vector3();

const rand = (a, b) => a + Math.random() * (b - a);
const pick = (weights) => {
  let s = 0; for (const k in weights) s += weights[k];
  let r = Math.random() * s;
  for (const k in weights) { r -= weights[k]; if (r <= 0) return k; }
  return Object.keys(weights)[0];
};

// ----------------------------------------------------------------------------------------- controller
export async function createCreature(scene, loader, { flashlight, camera, sound, physics, boxes, nav, onEvent, onJumpscare, onBlackout, onReturn, onScare, onCross } = {}) {
  const actor = await loadActor(loader);
  const { root, meta } = actor;
  root.visible = false;
  scene.add(root);
  const ghost = actor.another();
  ghost.root.visible = false;
  scene.add(ghost.root);

  // ---- its body in the physics world: a 75 kg capsule, always moved by forces, never teleported through things.
  // Walls and furniture stop it; boxes it shoves aside with ~3 kN, far more than any pile of them resists (an 80 kg
  // box slides at ~350 N), so a barricade slows it but does not hold it. Only the jumpscare and hiding switch it to
  // kinematic.
  const MASS = 90, HUNT_FORCE = 3200, WALK_FORCE = 3200;
  let body = null, collider = null, dynamic = false;
  const drive = { x: 0, z: 0, speed: 0, force: WALK_FORCE };
  if (physics) {
    const { RAPIER, world } = physics;
    body = world.createRigidBody(RAPIER.RigidBodyDesc.kinematicPositionBased().setTranslation(0, -10, 0).lockRotations());
    collider = world.createCollider(RAPIER.ColliderDesc.capsule(0.6, 0.24).setTranslation(0, 0.86, 0)
      .setMass(MASS).setFriction(0), body);
    collider.setEnabled(false);
    physics.creatureBody = body;
  }
  function setDynamic(on) {
    if (!body) return;
    const { RAPIER } = physics;
    dynamic = on;
    body.setBodyType(on ? RAPIER.RigidBodyType.Dynamic : RAPIER.RigidBodyType.KinematicPositionBased, true);
    body.setTranslation({ x: root.position.x, y: 0, z: root.position.z }, true);
    body.setLinvel({ x: 0, y: 0, z: 0 }, true);
    drive.speed = 0;
  }

  let job = null, jobName = null;
  let nextAt = performance.now() / 1000 + rand(3, 5);
  const bornAt = performance.now() / 1000;
  let nextHuntAt = performance.now() / 1000 + rand(80, 110);
  let hunting = false, stunned = false, flashAt = -1e9;
  let items = null;                           // candles, flares, music boxes (set after creation)
  let baitBox = null, baitSeen = new Map();   // box id -> when it was first seen lying in the corridor
  const taken = [];                            // files it carried off, and when they come back
  let last = null, count = 0, lastScare = performance.now() / 1000, voiceIn = rand(12, 20);
  const tmp = v3(), head = v3(), chest = v3();

  const faceAngle = (dx, dz) => Math.atan2(dx, dz);   // model faces +Z

  /** line of sight between two points: walls, door leaves, furniture and your boxes all block it */
  function seenThroughDoor(a, b) {
    if (!physics) return true;
    const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z, L = Math.hypot(dx, dy, dz);
    if (L < 0.3) return true;
    return physics.cast([a.x, a.y, a.z], [dx / L, dy / L, dz / L], L).dist >= L - 0.3;
  }

  // ---- the hallway: doors (from the environment's Door_* / Inside_* empties)
  const doors = nav.doors;
  const out = (d, k) => [d.door.x + d.into.x * k, d.door.z + d.into.z * k];   // k > 0: into the hallway
  const exitPath = (d) => [[d.inside.x, d.inside.z], out(d, -0.3), out(d, 0.75)];
  const enterPath = (d) => [out(d, 0.75), out(d, -0.3), [d.inside.x, d.inside.z]];
  const pickDoor = (f = () => true) => { const c = doors.filter(f); return c[Math.floor(Math.random() * c.length)] || doors[0]; };
  const nearestDoor = (p, f = () => true) => doors.filter(f).reduce((best, d) => {
    const dd = Math.hypot(d.door.x - p.x, d.door.z - p.z);
    return !best || dd < best.dd ? { d, dd } : best;
  }, null)?.d || doors[0];
  const inSideRoom = (p) => p.x < HALL.x0 - 0.05 || p.x > HALL.x1 + 0.05;
  if (boxes) boxes.setBaitTest((p) => inSideRoom(p) || doors.some((d) => Math.hypot(d.door.x - p.x, d.door.z - p.z) < 1.2));
  const place = (x, z, yaw) => {
    root.position.set(x, 0, z); root.rotation.set(0, yaw, 0); root.visible = true;
    contacts.clear();
    setDynamic(true); drive.force = WALK_FORCE;
  };
  const now = () => performance.now() / 1000;
  /** you are building: something was dropped or dragged in the last 10 s */
  const building = () => boxes && now() - boxes.lastBuild < 10;

  /** how strongly the beam is on the creature right now (0..1), counting only what the camera can see */
  function litness() {
    if (!root.visible) return 0;
    actor.headPos(head);
    chest.set(root.position.x, 1.25, root.position.z);
    let best = performance.now() - flashAt < 300 && inView() ? 1 : 0;
    if (items) best = Math.max(best, items.lightAt(chest), items.lightAt(head));
    for (const p of [head, chest]) {
      if (!seenThroughDoor(flashlight.pos, p) || !seenThroughDoor(camera.position, p)) continue;
      best = Math.max(best, flashlight.exposure(p));
    }
    return best;
  }

  // Footfalls from the feet themselves. A foot in the air travels fast; a planted foot is still on the floor (the body
  // moves over it). A step sounds at the moment a foot goes from swinging to planted, as loud as it was swung. So a
  // slow shuffle gives slow, soft steps and a sprint fast, heavy ones, always in time with what you see.
  const contacts = new Map();
  let clock = 0;                                    // game time (advances with update(dt))
  function footsteps() {
    if (!root.visible) return;
    const kind = actor.clip === 'crawl' || actor.clip === 'drag' ? 'crawl' : 'run';
    const now = clock;
    for (const [name, p] of actor.contactPoints()) {
      let c = contacts.get(name);
      if (!c || now - c.t > 0.3) { contacts.set(name, { p: p.clone(), t: now, swing: 0, planted: true, last: now }); continue; }
      const dtc = now - c.t;
      if (dtc < 1 / 90) continue;
      const v = p.distanceTo(c.p) / dtc;
      c.swing = Math.max(c.swing * Math.exp(-dtc * 3), v);
      if (!c.planted && v < 0.3 && p.y < 0.14 && now - c.last > 0.16) {
        c.planted = true; c.last = now;
        const occluded = !seenThroughDoor(camera.position, tmp.set(p.x, 0.3, p.z));
        // loudness: mostly how fast the body is going (a heavy sprint vs a shuffle), a little how hard it was swung
        const bodyV = body ? Math.hypot(body.linvel().x, body.linvel().z) : 1;
        const gain = THREE.MathUtils.clamp(0.15 + 0.85 * bodyV / meta.run.speed + c.swing / 14, 0.12, 1.3);
        sound && sound.footstep({ pos: p.clone(), kind, occluded, gain });
        c.swing = 0;
      } else if (c.planted && v > 0.7) c.planted = false;
      c.p.copy(p); c.t = now;
    }
  }

  /** is it on screen and in the line of sight (in the room, or seen through the doorway)? */
  function inView() {
    if (!root.visible) return false;
    actor.headPos(head);
    if (!seenThroughDoor(camera.position, head)) return false;
    tmp.copy(head).project(camera);
    return Math.abs(tmp.x) < 1.05 && Math.abs(tmp.y) < 1.05 && tmp.z < 1;
  }
  const distToCamera = () => Math.hypot(root.position.x - camera.position.x, root.position.z - camera.position.z);

  // ---- coroutine helpers
  function* wait(sec) { let t = 0; while (t < sec) t += yield; }

  /**
   * Walk a polyline under its own power: the drive pushes the body towards each waypoint, the gait follows the speed
   * it actually makes (so feet do not skate, and it strains against what is in the way). Returns false if it got
   * stuck for 2.5 s (a wall, or a barricade too heavy for its walking force).
   */
  function* travel(points, clip, { speed = meta[clip].speed, accel = 14, startSpeed = speed, turnRate = 9, force = drive.force } = {}) {
    let v = startSpeed, stuck = 0;
    drive.force = force;
    for (let i = 1; i < points.length; i++) {
      const [bx, bz] = points[i];
      const last = i === points.length - 1;
      while (true) {
        const dx = bx - root.position.x, dz = bz - root.position.z, d = Math.hypot(dx, dz);
        if (d < (last ? 0.2 : 0.45)) break;
        const dt = yield;
        v = Math.min(speed, v + accel * dt);
        drive.x = dx / d; drive.z = dz / d; drive.speed = v;
        if (!body) { root.position.x += drive.x * v * dt; root.position.z += drive.z * v * dt; }
        let t = faceAngle(dx, dz) - root.rotation.y; t = Math.atan2(Math.sin(t), Math.cos(t));
        root.rotation.y += t * Math.min(1, turnRate * dt);
        const made = body ? Math.hypot(body.linvel().x, body.linvel().z) : v;
        actor.setTimeScale(Math.max(0.2, made / meta[clip].speed));
        footsteps();
        stuck = made < v * 0.25 ? stuck + dt : Math.max(0, stuck - dt);
        if (stuck > 0.7 && boxesAhead()) {
          // boxes in its way (wedged in a doorway, say): it tears through them
          const keep = actor.clip;
          drive.speed = 0;
          yield* bash();
          actor.play(keep, { fade: 0.2 });
          stuck = 0;
          continue;
        }
        if (stuck > 2.5) { drive.speed = 0; return false; }
      }
    }
    drive.speed = 0;
    return true;
  }

  function boxesAhead() {
    if (!boxes) return false;
    const fx = Math.sin(root.rotation.y), fz = Math.cos(root.rotation.y);
    return boxes.near(new THREE.Vector3(root.position.x + fx * 0.55, 0, root.position.z + fz * 0.55), 1.0).length > 0;
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

  /** caught on the way somewhere: it screams at you and runs into the nearest room */
  function* bolt() {
    scared = false;
    yield* screamAtYou();
    actor.play('run', { fade: 0.15 });
    const d = nearestDoor(root.position);
    yield* travel([[root.position.x, root.position.z], ...enterPath(d)], 'run', { startSpeed: 1, accel: 10 });
  }

  /** from one room across or along the hallway into another; the beam on it makes it bolt. With `flash`, the sky
   *  lights up at the moment it is out in the open */
  function* roomToRoom(a, b, clip, speed, { flash = false } = {}) {
    place(a.inside.x, a.inside.z, faceAngle(a.into.x, a.into.z));
    actor.play(clip, { fade: 0 });
    if (clip === 'walk' && Math.random() < 0.4 && sound && sound.voice) sound.voice('moan', { pos: a.inside.clone().setY(1.6), gain: 0.7, occluded: true });
    const path = [...exitPath(a), ...enterPath(b)];
    let flashed = !flash;
    const ok = yield* travelWatchful(path, clip, speed, () => litness() > 0.2, () => {
      if (!flashed && Math.abs(root.position.x) < 0.45) { flashed = true; onCross && onCross(); }
    });
    if (!ok) yield* bolt();
  }
  const across = (a) => doors.filter((d) => d.side !== a.side).sort((x, y) => Math.abs(x.door.z - a.door.z) - Math.abs(y.door.z - a.door.z))[0];

  // ---- events
  const EVENTS = {
    /** out of one room and straight across the hallway into the room opposite */
    *cross() {
      const a = pickDoor(), b = across(a);
      const run = Math.random() < 0.35;
      yield* roomToRoom(a, b, run ? 'run' : 'walk', run ? meta.run.speed : meta.walk.speed * 2.4);
    },
    /** out of a room and along the hallway, to a room further down or nearer you */
    *wander() {
      const a = pickDoor();
      const b = pickDoor((d) => d !== a && Math.abs(d.door.z - a.door.z) > 3) || across(a);
      yield* roomToRoom(a, b, 'walk', meta.walk.speed * 2);
    },
    /** a sprint across the hallway (usually with lightning as it crosses, so you see it for that instant) */
    *dash() {
      const a = pickDoor((d) => d.door.z < -3.5), b = across(a);
      yield* roomToRoom(a, b, 'run', meta.run.speed * 1.15, { flash: Math.random() < 0.7 });
    },
    /** the torch dies; when it comes back on it is right in front of you, screaming; then it is not */
    *scare() {
      flashlight.toggle(false);
      sound && sound.click(false);
      yield* wait(rand(0.9, 1.5));
      const fwd = camera.getWorldDirection(new THREE.Vector3()); fwd.y = 0; fwd.normalize();
      const x = camera.position.x + fwd.x * 1.35 + rand(-0.1, 0.1) - 0.1, z = camera.position.z + fwd.z * 1.35;
      ghost.root.position.set(x, 0, z);
      ghost.root.rotation.set(0, faceAngle(camera.position.x - x, camera.position.z - z), 0);
      ghost.play('scream', { loop: false, fade: 0 }); ghost.update(0.5);
      ghost.root.visible = true; ghost.root.updateMatrixWorld(true);
      ghost.headPos(head);
      flashlight.toggle(true);
      flashlight.aimAt(head.clone().add(new THREE.Vector3(0, -0.1, 0)), true);
      sound && sound.shriek();
      onScare && onScare();
      let t = 0;
      while (t < 0.42) { const dt = yield; t += dt; ghost.update(dt); }
      flashlight.toggle(false);
      ghost.root.visible = false;
      yield* wait(0.7);
      flashlight.toggle(true);
    },
    /** across on all fours */
    *crawl() {
      const a = pickDoor((d) => d.door.z < -4), b = across(a);
      const clip = actor.has('crawl') ? 'crawl' : 'run';
      yield* roomToRoom(a, b, clip, meta[clip].speed);
    },
    /** stands just inside a doorway, half out, watching you; the beam sends it back in */
    *peek() {
      const d = pickDoor((x) => x.door.z < -3);
      const [px, pz] = out(d, -0.3);
      place(px, pz, faceAngle(camera.position.x - px, camera.position.z - pz));
      setDynamic(false);                 // it stands still against the jamb
      actor.play('idle', { fade: 0 });
      let seen = 0, t = 0;
      const patience = rand(8, 14);
      while (t < patience) {
        const dt = yield; t += dt;
        actor.setEyeGlow(eyeGlow());
        seen = litness() > 0.2 ? seen + dt : Math.max(0, seen - dt * 0.5);
        if (seen > 0.15) break;
      }
      setDynamic(true);
      if (seen > 0.15) { yield* screamAtYou(); actor.play('run', { fade: 0.15 }); yield* travel([[root.position.x, root.position.z], [d.inside.x, d.inside.z]], 'run', { startSpeed: 1 }); }
      else { actor.play('walk', { fade: 0.3 }); yield* travel([[root.position.x, root.position.z], [d.inside.x, d.inside.z]], 'walk', { speed: meta.walk.speed * 1.5 }); }
    },
    /** a figure at the far end, against the window; when it is found it walks into the last room */
    *endwatch() {
      const x = rand(-0.35, 0.35), z = nav.end.z + 0.6;
      place(x, z, faceAngle(camera.position.x - x, camera.position.z - z));
      setDynamic(false);
      actor.play('idle', { fade: 0 });
      let seen = 0, t = 0;
      const patience = rand(10, 18);
      while (t < patience) {
        const dt = yield; t += dt;
        actor.setEyeGlow(eyeGlow());
        seen = litness() > 0.12 ? seen + dt : Math.max(0, seen - dt * 0.5);
        if (seen > 0.6) break;
      }
      setDynamic(true);
      const d = nearestDoor(root.position);
      actor.play('walk', { fade: 0.3 });
      yield* travel([[root.position.x, root.position.z], ...enterPath(d)], 'walk', { speed: meta.walk.speed * (seen > 0.6 ? 2.6 : 1.4) });
    },
    *hunt() {
      hunting = true; stunned = false;
      sound && sound.drone(true);
      flashlight.stutter(0.9);
      // it comes out of one of the far rooms and down the hallway at you; whatever you piled up is in its way
      const from = pickDoor((d) => d.door.z < -6);
      place(from.inside.x, from.inside.z, faceAngle(from.into.x, from.into.z));
      drive.force = HUNT_FORCE;
      const leave = exitPath(from).slice(1);         // waypoints out of its room
      let grace = 0;
      let flicker = rand(4, 7), blocked = 0, clip = null, detour = 0, detourSide = 1;
      let huntTime = 0, best = Infinity, sinceBest = 0;
      // you hear it before you see it: wet, ragged breathing that comes with it
      const breath = sound && sound.voice && sound.voice('breath_close', { pos: root.position.clone().setY(1.6), loop: true, gain: 1.1, fadeIn: 1.5 });
      let growlIn = rand(4, 9);
      while (true) {
        const dt = yield;
        huntTime += dt;
        if (breath) breath.setPos(actor.headPos(head));
        growlIn -= dt;
        if (growlIn < 0 && sound && sound.voice) { sound.voice('growl', { pos: actor.headPos(head).clone(), gain: 0.8 }); growlIn = rand(5, 11); }
        // never stuck for ever: no progress towards you for 8 s (or 70 s in all) and it goes back to its room
        const dc = distToCamera();
        if (dc < best - 0.25) { best = dc; sinceBest = 0; } else if (!building()) sinceBest += dt;
        if (sinceBest > 8 || huntTime > 70) stunned = true;
        if (stunned) { yield* retreat(); break; }
        if (distToCamera() < 0.95) { yield* jumpscare(); break; }
        flicker -= dt;
        if (flicker < 0) { flashlight.stutter(rand(0.3, 0.7)); flicker = rand(4.5, 9); }
        actor.setEyeGlow(eyeGlow());
        // a flare's light on it: it shrieks and backs off, like from the camera flash
        if (items && items.flareAt(chest.set(root.position.x, 1.2, root.position.z)) > 1.2) { stunned = true; continue; }
        // you are still building: it waits in its room, out of sight (at most ~25 s per hunt)
        if (building() && grace < 25 && leave.length === 2) {
          grace += dt;
          drive.speed = 0;
          if (clip !== 'idle') { actor.play('idle', { fade: 0.4 }); clip = 'idle'; }
          continue;
        }
        const dark = !flashlight.on || flashlight.output < 0.13;
        const want = dark ? 'run' : 'walk';
        if (clip !== want) { actor.play(want, { fade: 0.25 }); clip = want; }
        // candlelight: it hates it, and drags itself through it slowly
        const candle = items ? items.lightAt(chest.set(root.position.x, 1.2, root.position.z)) : 0;
        const speed = (dark ? meta.run.speed : meta.walk.speed * 2.3) * (candle > 0.2 ? 0.35 : 1);
        // out of its room, then down the hallway at you; a music box playing comes first (through its doorway if
        // it is in a side room)
        const lure = items && items.lure();
        let tx, tz;
        if (leave.length) {
          [tx, tz] = leave[0];
          if (Math.hypot(tx - root.position.x, tz - root.position.z) < 0.4) { leave.shift(); continue; }
        } else if (lure) {
          const ld = inSideRoom(lure.pos) ? nearestDoor(lure.pos) : null;
          const meIn = inSideRoom(root.position);
          if (ld && !meIn && Math.hypot(...out(ld, 0.5).map((v, i) => v - (i ? root.position.z : root.position.x))) > 0.4) [tx, tz] = out(ld, 0.5);
          else { tx = lure.pos.x; tz = lure.pos.z; }
        } else { tx = camera.position.x; tz = camera.position.z - 0.2; }
        if (detour > 0) {
          // walking round something solid: aim off to the side for a moment
          detour -= dt;
          const a = Math.atan2(tx - root.position.x, tz - root.position.z) + detourSide * 1.1;
          tx = root.position.x + Math.sin(a); tz = root.position.z + Math.cos(a);
        }
        if (lure && Math.hypot(lure.pos.x - root.position.x, lure.pos.z - root.position.z) < 0.7) {
          // it stops to listen, and then it breaks it
          drive.speed = 0; actor.play('idle', { fade: 0.3 }); clip = null;
          yield* wait(rand(4, 7));
          actor.play(actor.has('attack') ? 'attack' : 'idle', { loop: false, fade: 0.15 });
          yield* wait(0.9);
          items.smash(lure.item);
          yield* wait(1.2);
          continue;
        }
        const dx = tx - root.position.x, dz = tz - root.position.z, d = Math.hypot(dx, dz) || 1;
        drive.x = dx / d; drive.z = dz / d; drive.speed = speed;
        let turn = faceAngle(drive.x, drive.z) - root.rotation.y; turn = Math.atan2(Math.sin(turn), Math.cos(turn));
        root.rotation.y += turn * Math.min(1, 6 * dt);
        // the gait follows the speed it actually makes against whatever is in the way
        const v = body ? Math.hypot(body.linvel().x, body.linvel().z) : speed;
        actor.setTimeScale(Math.max(0.25, v / meta[want].speed));
        footsteps();
        blocked = v < speed * 0.2 ? blocked + dt : Math.max(0, blocked - dt);
        if (blocked > 0.7) {
          const fx = Math.sin(root.rotation.y), fz = Math.cos(root.rotation.y);
          const front = new THREE.Vector3(root.position.x + fx * 0.55, 0, root.position.z + fz * 0.55);
          if (boxes && boxes.near(front, 0.9).length && actor.has('attack')) { yield* bash(); clip = null; }
          else { detour = 1.1; detourSide = Math.random() < 0.5 ? -1 : 1; }      // furniture: go round it
          blocked = 0;
        }
      }
      hunting = false;
      if (breath) breath.stop(1.2);
      sound && sound.drone(false);
      nextHuntAt = performance.now() / 1000 + rand(100, 160);
    },
    /**
     * Bait: a box left out in the corridor. It comes for it from the far end, bends to pick it up and carries it off
     * into the dark. Caught in the beam on the way, it drops it and runs. A taken file comes back later, chewed.
     */
    *fetch() {
      const b = baitBox; baitBox = null;
      if (!b || !boxes.boxes.has(b.id)) return;
      const bt = b.body.translation();
      const d = nearestDoor(bt);
      place(d.inside.x, d.inside.z, faceAngle(d.into.x, d.into.z));
      const quick = meta.walk.speed * 2.6;
      actor.play('walk', { fade: 0 });
      // to the box: through its doorway unless the box is in the room with it
      const reach = (b.size.w / 2) + 0.45;
      const dx = bt.x - d.inside.x, dz = bt.z - d.inside.z, dd = Math.hypot(dx, dz) || 1;
      const stop = [bt.x - dx / dd * reach, bt.z - dz / dd * reach];
      const path = inSideRoom(bt) && Math.sign(bt.x) === Math.sign(d.inside.x) ? [[d.inside.x, d.inside.z], stop] : [[d.inside.x, d.inside.z], out(d, -0.3), stop];
      yield* travelWatchful(path, 'walk', quick, () => litness() > 0.2);
      if (scared) { yield* bolt(); return; }
      root.rotation.y = faceAngle(bt.x - root.position.x, bt.z - root.position.z);
      const dur = actor.play(actor.has('attack') ? 'attack' : 'idle', { loop: false, fade: 0.2 });
      let t = 0, held = false;
      const p = new THREE.Vector3(), q = new THREE.Quaternion();
      const hold = () => { actor.carryPos(p); q.setFromEuler(new THREE.Euler(0, root.rotation.y, 0)); boxes.holdAt(b, p, q); };
      while (t < Math.min(dur, 1.6)) {
        const dt = yield; t += dt;
        if (!held && t > 0.55) { held = true; boxes.carry(b); sound && sound.thud({ pos: root.position.clone(), strength: 0.5, size: b.size.t }); }
        if (held) hold();
      }
      actor.play('walk', { fade: 0.25 });
      const back = inSideRoom(root.position) ? [[root.position.x, root.position.z], [d.inside.x, d.inside.z]] : [[root.position.x, root.position.z], ...enterPath(d)];
      const ok = yield* travelWatchful(back, 'walk', quick, () => litness() > 0.2, hold);
      if (!ok) { boxes.letGo(b); yield* bolt(); return; }
      boxes.consume(b);
      taken.push({ id: b.id, at: performance.now() / 1000 + rand(25, 45) });
      nextHuntAt = Math.max(nextHuntAt, performance.now() / 1000 + 45);   // busy with that, not coming for you
    },
  };

  /** travel, but give up (return false) the moment `spooked()` is true; `each` runs every frame */
  let scared = false;
  function* travelWatchful(points, clip, speed, spooked, each) {
    const g = travel(points, clip, { speed, startSpeed: speed * 0.6, accel: 4 });
    g.next();
    let seen = 0;
    while (true) {
      const dt = yield;
      seen = spooked() ? seen + dt : Math.max(0, seen - dt);
      if (seen > 0.3) { scared = true; return false; }
      const r = g.next(dt);
      if (each) each();
      if (r.done) return true;
    }
  }

  /** stuck behind boxes: it beats at them (two blows per attack clip) */
  function* bash() {
    drive.speed = 0;
    const dur = actor.play('attack', { loop: false, fade: 0.15 });
    const hits = [0.32, 0.62].map((f) => f * dur);
    let t = 0, h = 0;
    while (t < dur) {
      const dt = yield;
      if (stunned) return;
      actor.setTimeScale(1);
      t += dt;
      if (h < hits.length && t >= hits[h]) {
        h++;
        const fx = Math.sin(root.rotation.y), fz = Math.cos(root.rotation.y);
        const front = new THREE.Vector3(root.position.x + fx * 0.55, 0, root.position.z + fz * 0.55);
        const hit = boxes ? boxes.near(front, 1.0) : [];
        for (const b of hit) {
          if (boxes.damage(b, 1.5, { x: fx, z: fz })) continue;          // torn apart
          b.body.applyImpulse({ x: fx * 150, y: 55, z: fz * 150 }, true);
          b.body.applyTorqueImpulse({ x: rand(-6, 6), y: rand(-6, 6), z: rand(-6, 6) }, true);
        }
        sound && sound.thud({ pos: front, strength: hit.length ? 1.4 : 0.4, size: 0.9 });
      }
    }
  }

  /** the flash got it: it screams and runs back out into the corridor */
  function* retreat() {
    stunned = false;
    drive.speed = 0; drive.force = WALK_FORCE;
    yield* screamAtYou();
    sound && sound.voice && sound.voice('scream_far', { pos: root.position.clone().setY(1.6), gain: 0.9 });
    actor.play('run', { fade: 0.15 });
    const p = root.position;
    // into the nearest room that is not behind you
    const d = nearestDoor(p, (x) => x.door.z < p.z + 0.5) || nearestDoor(p);
    yield* travel([[p.x, p.z], ...enterPath(d)], 'run', { startSpeed: 1, accel: 12 });
  }

  /** it reached you */
  function* jumpscare() {
    setDynamic(false);
    if (collider) collider.setEnabled(false);
    const fx = camera.position.x, fz = camera.position.z;
    const fwd = camera.getWorldDirection(new THREE.Vector3()); fwd.y = 0; fwd.normalize();
    // right in front of you, face to face, screaming
    place(fx + fwd.x * 0.8, fz + fwd.z * 0.8, faceAngle(-fwd.x, -fwd.z));
    actor.play(actor.has('scream') ? 'scream' : 'idle', { loop: false, fade: 0, timeScale: 0.9 });
    actor.update(0.45 / 0.9);                // reared back, about to lunge
    root.updateMatrixWorld(true);
    // the scream pose leans far forward: move the whole body so the face ends up just in front of the lens
    actor.headPos(head);
    // its lunge then carries the face ~0.6 m forward and down, into the lens
    const want = camera.position.clone().addScaledVector(camera.getWorldDirection(new THREE.Vector3()), 0.95);
    want.y += 0.05;
    root.position.x += want.x - head.x;
    root.position.z += want.z - head.z;
    root.position.y = THREE.MathUtils.clamp(want.y - head.y, -0.5, 0.5);
    root.updateMatrixWorld(true);
    sound && sound.shriek();
    actor.headPos(head);
    flashlight.aimAt(head.clone().add(new THREE.Vector3(0, -0.05, 0)), true);
    onJumpscare && onJumpscare();
    yield* wait(0.42);                       // cut to black at the peak of the lunge, before it bends away
    onBlackout && onBlackout(true);
    flashlight.toggle(false);
    root.visible = false; root.position.y = 0;
    yield* wait(1.8);
    flashlight.toggle(true);
    onBlackout && onBlackout(false);
  }

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
    onEvent && onEvent(name);
    return true;
  }

  function schedule() {
    const now = performance.now() / 1000;
    // fast runs across are the hook: it opens with three sprints, and after that ~70% of what it does is running or
    // crawling (dash, crawl), the rest the slow, standing kinds (wander, peek, the far window, a walk across)
    const w = { dash: 45, crawl: 25, cross: 9, wander: 8, peek: 8, endwatch: 5 };
    if (!actor.has('peek')) delete w.peek;
    if (count < 3) { start('dash'); return; }
    if (now >= nextHuntAt) { start('hunt'); return; }
    if (last && w[last] && last !== 'dash') w[last] *= 0.3;
    if (now - lastScare > 70 && now - bornAt > 40 && Math.random() < 0.3) { lastScare = now; start('scare'); return; }
    start(pick(w));
  }

  const SPOTS = [
    // places to stand in a photo it was not in: behind the bed, in the doorway, much too close, the far corner
    // in a doorway, at the far window, much too close on your left, by the first door on the right
    () => out(pickDoor(), -0.15), () => [rand(-0.3, 0.3), nav.end.z + 0.6],
    () => [camera.position.x - 0.95, camera.position.z - 1.6], () => [0.85, -3.6],
  ];

  return {
    actor,
    get busy() { return !!job; },
    get event() { return jobName; },
    get hunting() { return hunting; },
    get lit() { return litness(); },
    get contacts() { return actor.contactPoints().map(([n, p]) => n + ':' + p.y.toFixed(3)); },
    setItems(v) { items = v; },
    trigger(name) { if (job) return false; return start(name); },
    /** the camera flashed: anything in view counts as caught; during a hunt it is driven back */
    onFlash() {
      flashAt = performance.now();
      if (hunting && inView() && distToCamera() < 7) stunned = true;
    },
    /** put it somewhere in the room for one rendered frame (the photo); returns a function that removes it */
    stageForPhoto() {
      if (hunting) return null;
      const [x, z] = SPOTS[Math.floor(Math.random() * SPOTS.length)]();
      ghost.root.position.set(x, 0, z);
      ghost.root.rotation.set(0, faceAngle(camera.position.x - x, camera.position.z - z), 0);
      ghost.play('idle', { fade: 0 });
      ghost.update(rand(0.5, 3.5));
      ghost.root.visible = true;
      ghost.root.updateMatrixWorld(true);
      return () => { ghost.root.visible = false; };
    },
    /** lightning: for the length of the flash it may be standing at the far end, or in a far doorway */
    stageForLightning() {
      if (job || hunting || Math.random() > 0.4) return null;
      const far = Math.random() < 0.5;
      const [x, z] = far ? [rand(-0.3, 0.3), nav.end.z + 0.7] : out(pickDoor((d) => d.door.z < -7), -0.1);
      ghost.root.position.set(x, 0, z);
      ghost.root.rotation.set(0, faceAngle(camera.position.x - x, camera.position.z - z), 0);
      ghost.play('idle', { fade: 0 }); ghost.update(rand(0.5, 3.5));
      ghost.root.visible = true; ghost.root.updateMatrixWorld(true);
      return () => { ghost.root.visible = false; };
    },
    /** before each physics step: kinematic follow, or the hunting drive */
    beforeStep(dt) {
      if (!body) return;
      const show = root.visible && !!job;
      if (collider.isEnabled() !== show) collider.setEnabled(show);
      if (!show) { drive.speed = 0; return; }
      if (!dynamic) {
        body.setNextKinematicTranslation({ x: root.position.x, y: 0, z: root.position.z });
        return;
      }
      const lv = body.linvel();
      let jx = MASS * (drive.x * drive.speed - lv.x), jz = MASS * (drive.z * drive.speed - lv.z);
      const j = Math.hypot(jx, jz), cap = drive.force * dt;
      if (j > cap) { jx *= cap / j; jz *= cap / j; }
      body.applyImpulse({ x: jx, y: 0, z: jz }, true);
    },
    afterStep() {
      if (!body || !dynamic) return;
      const t = body.translation();
      root.position.x = t.x; root.position.z = t.z;
    },
    update(dt) {
      clock += dt;
      actor.update(dt);
      const now = performance.now() / 1000;
      // bait: a box lying in the corridor draws it (candy at once)
      if (boxes) {
        const lying = boxes.bait();
        for (const id of [...baitSeen.keys()]) if (!lying.some((b) => b.id === id)) baitSeen.delete(id);
        for (const b of lying) if (!baitSeen.has(b.id)) baitSeen.set(b.id, now + (/candy/i.test(b.icon.name) ? 1.5 : rand(4, 9)));
        if (!job && !building()) {
          const ready = lying.find((b) => baitSeen.get(b.id) <= now);
          if (ready) { baitBox = ready; baitSeen.delete(ready.id); start('fetch'); }
        }
      }
      // the house is never quite silent: moans behind walls, a breath from a far room, rarely a child's giggle, and if
      // you sit in the dark, a whisper right next to you
      voiceIn -= dt;
      if (voiceIn < 0 && !hunting && sound && sound.voice) {
        voiceIn = rand(22, 55);
        const r = Math.random();
        const d = pickDoor((x) => x.door.z < -3);
        if (!flashlight.on && r < 0.35) sound.voice(Math.random() < 0.5 ? 'whisper' : 'laugh_whisper', { pos: camera.position.clone().add(new THREE.Vector3(rand(-0.6, 0.6), 0, 0.3)), gain: 0.55, wet: false });
        else if (r < 0.5) sound.voice('moan', { pos: d.inside.clone().setY(1.6), gain: 0.6, occluded: true });
        else if (r < 0.75) sound.voice('breath_far', { pos: d.inside.clone().setY(1.6), gain: 0.6, occluded: true });
        else if (r < 0.88) sound.voice('laugh_child', { pos: pickDoor((x) => x.door.z < -8).inside.clone().setY(1.2), gain: 0.4, occluded: true });
        else sound.voice('moan', { pos: d.inside.clone().setY(1.6), gain: 0.5, occluded: true });
      }
      // what it took comes back, chewed
      for (let i = taken.length - 1; i >= 0; i--) {
        if (taken[i].at > now) continue;
        const { id } = taken.splice(i, 1)[0];
        onReturn && onReturn(id);
      }
      if (!job && building()) nextAt = Math.max(nextAt, now + 3);   // nothing comes past while you build
      if (!job && now >= nextAt) schedule();
      if (job) {
        const r = job.next(dt);
        if (r.done) {
          job = null; jobName = null; root.visible = false; actor.setEyeGlow(0);
          setDynamic(false);
          nextAt = now + (now - bornAt < 75 ? rand(5, 11) : rand(10, 26));
        }
      }
    },
  };
}
