// Files dropped onto the floor become moving boxes: corrugated cardboard, packing tape, the file's name in marker
// and its icon as a sticker. Size and mass come from the file's size (an empty file is a 24 cm box of 1 kg, a disk
// image of several GB a 60 cm box of 80 kg). The hand that moves them is a spring with a force limit: light boxes
// lift and swing, heavy ones only slide, the way you would move them yourself.

import * as THREE from 'three';
import { BOUNDS as ROOM } from './layout.js';

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const HAND_FORCE = 380;       // N: about what one arm pulls without bracing
const HAND_K = 900, HAND_C = 60;

function sizeOf(bytes) {
  const t = clamp(Math.log10((bytes || 0) + 1) / 10, 0, 1);   // 0 B … 10 GB
  const e = 0.24 + 0.36 * t;
  const w = e * 1.25, h = e * 0.82, d = e;
  // cardboard plus contents: from crumpled paper (~40 kg/m³) to packed hardware (~380 kg/m³)
  const density = 40 + 340 * t * t;
  return { w, h, d, t, mass: Math.max(0.6, w * h * d * density) };
}

// ------------------------------------------------------------------------------------------------ textures
let baseCanvas = null;
function cardboardBase() {
  if (baseCanvas) return baseCanvas;
  const c = document.createElement('canvas'); c.width = c.height = 512;
  const g = c.getContext('2d');
  g.fillStyle = '#9a7349'; g.fillRect(0, 0, 512, 512);
  // fibres and blotches
  for (let i = 0; i < 9000; i++) {
    const l = Math.random();
    g.fillStyle = `rgba(${l < 0.5 ? '60,40,20' : '190,150,100'},${Math.random() * 0.08})`;
    g.fillRect(Math.random() * 512, Math.random() * 512, 1 + Math.random() * 3, 1);
  }
  for (let i = 0; i < 40; i++) {
    const x = Math.random() * 512, y = Math.random() * 512, r = 20 + Math.random() * 70;
    const grd = g.createRadialGradient(x, y, 0, x, y, r);
    grd.addColorStop(0, `rgba(50,32,15,${0.05 + Math.random() * 0.1})`); grd.addColorStop(1, 'rgba(50,32,15,0)');
    g.fillStyle = grd; g.fillRect(x - r, y - r, 2 * r, 2 * r);
  }
  // flutes seen through the liner
  for (let y = 0; y < 512; y += 6) { g.fillStyle = 'rgba(70,50,30,0.05)'; g.fillRect(0, y, 512, 2); }
  // scuffed edges
  g.strokeStyle = 'rgba(40,25,10,0.35)'; g.lineWidth = 10; g.strokeRect(0, 0, 512, 512);
  baseCanvas = c;
  return c;
}

function faceTexture(name, iconImg, { tape = false, label = false } = {}) {
  const c = document.createElement('canvas'); c.width = c.height = 512;
  const g = c.getContext('2d');
  g.drawImage(cardboardBase(), 0, 0);
  if (tape) {
    // packing tape down the middle, slightly glossy and wrinkled
    g.fillStyle = 'rgba(205,170,110,0.55)'; g.fillRect(0, 210, 512, 92);
    for (let i = 0; i < 30; i++) { g.fillStyle = `rgba(255,240,200,${Math.random() * 0.12})`; g.fillRect(Math.random() * 512, 210 + Math.random() * 92, 30 + Math.random() * 80, 2); }
  }
  if (label) {
    // the name in black marker, a bit crooked, and the icon as a sticker
    g.save();
    g.translate(256, 300); g.rotate((Math.random() - 0.5) * 0.12);
    g.fillStyle = 'rgba(15,12,10,0.92)';
    let size = 64;
    const text = name.length > 22 ? name.slice(0, 20) + '…' : name;
    g.font = `700 ${size}px "Marker Felt", "Chalkboard SE", "Comic Sans MS", sans-serif`;
    while (g.measureText(text).width > 440 && size > 26) { size -= 4; g.font = `700 ${size}px "Marker Felt", "Chalkboard SE", "Comic Sans MS", sans-serif`; }
    g.textAlign = 'center'; g.fillText(text, 0, 70);
    g.restore();
    if (iconImg && iconImg.complete && iconImg.naturalWidth) {
      g.save(); g.translate(256, 170); g.rotate((Math.random() - 0.5) * 0.2);
      g.fillStyle = 'rgba(240,236,226,0.95)'; g.fillRect(-82, -82, 164, 164);
      g.drawImage(iconImg, -70, -70, 140, 140);
      g.restore();
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

let bumpTex = null;
function cardboardBump() {
  if (bumpTex) return bumpTex;
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const g = c.getContext('2d');
  g.fillStyle = '#808080'; g.fillRect(0, 0, 256, 256);
  for (let y = 0; y < 256; y += 3) { g.fillStyle = y % 6 ? '#8a8a8a' : '#767676'; g.fillRect(0, y, 256, 1); }
  for (let i = 0; i < 3000; i++) { g.fillStyle = `rgba(0,0,0,${Math.random() * 0.15})`; g.fillRect(Math.random() * 256, Math.random() * 256, 2, 2); }
  bumpTex = new THREE.CanvasTexture(c);
  bumpTex.wrapS = bumpTex.wrapT = THREE.RepeatWrapping;
  return bumpTex;
}

// ------------------------------------------------------------------------------------------------ boxes
export function createBoxes({ scene, physics, camera, desk, sound }) {
  const { RAPIER, world } = physics;
  const boxes = new Map();        // icon id -> { mesh, body, collider, mass, ... }
  const byHandle = new Map();     // collider handle -> box
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const v = new THREE.Vector3();

  function make(icon, at, yawAt = null) {
    const s = sizeOf(icon.bytes);
    const img = new Image(); img.src = icon.icon || '';
    const plain = () => new THREE.MeshStandardMaterial({ map: faceTexture(icon.name, null), bumpMap: cardboardBump(), bumpScale: 0.6, roughness: 0.9 });
    const labelled = () => new THREE.MeshStandardMaterial({ map: faceTexture(icon.name, img, { label: true }), bumpMap: cardboardBump(), bumpScale: 0.6, roughness: 0.88 });
    const top = new THREE.MeshStandardMaterial({ map: faceTexture(icon.name, null, { tape: true }), bumpMap: cardboardBump(), bumpScale: 0.6, roughness: 0.8 });
    // +x, -x, +y, -y, +z, -z
    const mats = [plain(), plain(), top, plain(), labelled(), labelled()];
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(s.w, s.h, s.d), mats);
    mesh.castShadow = mesh.receiveShadow = true;
    scene.add(mesh);
    // the sticker image may arrive after the first draw
    img.onload = () => { for (const i of [4, 5]) { mats[i].map.dispose(); mats[i].map = faceTexture(icon.name, img, { label: true }); mats[i].needsUpdate = true; } };

    // stacked boxes start square to the one below (a hand lines them up), others land at a random angle
    const yaw = yawAt !== null ? yawAt + (Math.random() - 0.5) * 0.12 : (Math.random() - 0.5) * 0.8;
    const tilt = yawAt !== null ? 0.02 : 0.15;
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler((Math.random() - 0.5) * tilt, yaw, (Math.random() - 0.5) * tilt));
    const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(at.x, at.y, at.z).setRotation(q)
      .setLinearDamping(0.05).setAngularDamping(0.2).setCcdEnabled(true));
    const collider = world.createCollider(RAPIER.ColliderDesc.cuboid(s.w / 2, s.h / 2, s.d / 2)
      .setMass(s.mass).setFriction(0.45).setRestitution(0.08)
      .setActiveEvents(RAPIER.ActiveEvents.CONTACT_FORCE_EVENTS)
      .setContactForceEventThreshold(25 * s.mass), body);
    const b = { id: icon.id, icon, mesh, body, collider, mass: s.mass, size: s };
    boxes.set(icon.id, b);
    byHandle.set(collider.handle, b);
    return b;
  }

  function remove(b) {
    scene.remove(b.mesh);
    b.mesh.geometry.dispose();
    for (const m of b.mesh.material) { m.map && m.map.dispose(); m.dispose(); }
    byHandle.delete(b.collider.handle);
    world.removeRigidBody(b.body);
    boxes.delete(b.id);
  }

  /**
   * Where a file dropped at the cursor would go, from a ray against everything solid (walls, furniture, boxes):
   * - onto a box: on top of it, lined up with it (that is how you stack a barricade);
   * - onto the floor or a piece of furniture's top: there;
   * - onto a wall or the side of furniture: just in front of it at that height, so it falls onto whatever is below.
   * The spot is raised until the new box does not overlap anything. Returns { pos, yaw, size } or null.
   */
  const tmpBox = new THREE.Box3();
  function dropTarget(clientX, clientY, bytes) {
    const s = sizeOf(bytes);
    ndc.set((clientX / innerWidth) * 2 - 1, -(clientY / innerHeight) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const o = ray.ray.origin, d = ray.ray.direction;
    // the creature's capsule is the only kinematic body: leave it out of the ray
    const creatureBody = physics.creatureBody;
    const hit = world.castRayAndGetNormal(new RAPIER.Ray(o, d), 12, true, undefined, undefined, undefined, creatureBody);
    if (!hit) return null;
    const p = new THREE.Vector3(o.x + d.x * hit.timeOfImpact, o.y + d.y * hit.timeOfImpact, o.z + d.z * hit.timeOfImpact);
    const n = hit.normal;
    if (n.y < -0.7) return null;                              // the ceiling
    const under = byHandle.get(hit.collider.handle);
    let pos, yaw = null;
    if (under) {
      const t = under.body.translation();
      tmpBox.setFromObject(under.mesh);
      // centred over the box below, nudged towards where you aimed
      pos = new THREE.Vector3(t.x + (p.x - t.x) * 0.3, tmpBox.max.y + s.h / 2 + 0.02, t.z + (p.z - t.z) * 0.3);
      const r = under.body.rotation();
      yaw = new THREE.Euler().setFromQuaternion(new THREE.Quaternion(r.x, r.y, r.z, r.w), 'YXZ').y;
    } else if (n.y > 0.7) {
      pos = new THREE.Vector3(p.x, p.y + s.h / 2 + 0.03, p.z);
    } else {
      const off = Math.max(s.w, s.d) / 2 + 0.04;
      pos = new THREE.Vector3(p.x + n.x * off, Math.max(p.y, s.h / 2 + 0.03), p.z + n.z * off);
    }
    // never inside the corridor's far wall or out of the room's sides
    pos.x = clamp(pos.x, ROOM.x0 + s.w / 2, ROOM.x1 - s.w / 2);
    pos.y = Math.min(pos.y, 2.3);
    // lift until it fits
    const shape = new RAPIER.Cuboid(s.w / 2, s.h / 2, s.d / 2);
    const rot = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, yaw || 0, 0));
    for (let i = 0; i < 30; i++) {
      const overlap = world.intersectionWithShape(pos, rot, shape, undefined, undefined, undefined, physics.creatureBody);
      if (!overlap) break;
      pos.y += 0.04;
    }
    return { pos, yaw, size: s };
  }

  // ghost of the box while a file is being dragged over the room
  const ghost = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
    new THREE.LineBasicMaterial({ color: 0xfff3dc, transparent: true, opacity: 0.55, depthTest: false }));
  ghost.renderOrder = 10;
  ghost.visible = false;
  scene.add(ghost);
  let dragIcon = null;
  desk.onIconDragStart((id) => { dragIcon = desk.getIcon(id); });
  desk.onIconDragEnd(() => { dragIcon = null; ghost.visible = false; });
  window.addEventListener('pointermove', (e) => {
    if (!dragIcon) return;
    const t = dropTarget(e.clientX, e.clientY, dragIcon.bytes);
    ghost.visible = !!t;
    if (!t) return;
    ghost.scale.set(t.size.w, t.size.h, t.size.d);
    ghost.position.copy(t.pos);
    ghost.rotation.set(0, t.yaw || 0, 0);
  }, true);

  // impacts: a box landing or being hit makes a hollow cardboard thump
  physics.onContactForce((e) => {
    const b = byHandle.get(e.collider1()) || byHandle.get(e.collider2());
    if (!b || !sound) return;
    const f = e.totalForceMagnitude();
    const now = performance.now();
    if (b.lastThud && now - b.lastThud < 90) return;
    b.lastThud = now;
    const p = b.body.translation();
    sound.thud({ pos: new THREE.Vector3(p.x, p.y, p.z), strength: clamp(f * physics.STEP / (b.mass * 1.2), 0.05, 1.5), size: b.size.t });
  });

  // ---- hand: grab a box with the mouse
  let baitTest = () => false;   // where a box counts as left out for it (set by the creature)
  let hand = null;
  let lastBuild = -1e9;          // when you last dropped or moved a box (it gives you time to build)
  function pick(clientX, clientY) {
    ndc.set((clientX / innerWidth) * 2 - 1, -(clientY / innerHeight) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hits = ray.intersectObjects([...boxes.values()].map((b) => b.mesh), false);
    if (!hits.length) return null;
    const b = [...boxes.values()].find((x) => x.mesh === hits[0].object);
    const local = b.mesh.worldToLocal(hits[0].point.clone());
    return { b, local, height: hits[0].point.y };
  }
  function handTarget(clientX, clientY) {
    // the grabbed point follows the cursor ray on a horizontal plane a little above where it was grabbed
    ndc.set((clientX / innerWidth) * 2 - 1, -(clientY / innerHeight) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const o = ray.ray.origin, d = ray.ray.direction;
    const y = hand.planeY;
    let t = Math.abs(d.y) > 1e-4 ? (y - o.y) / d.y : 20;
    if (!(t > 0)) t = 20;
    const p = o.clone().addScaledVector(d, Math.min(t, 9));
    p.x = clamp(p.x, ROOM.x0 + 0.2, ROOM.x1 - 0.2);
    p.z = clamp(p.z, ROOM.z0 + 0.3, ROOM.z1 - 0.3);
    return p;
  }

  window.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest && e.target.closest('.dk-icon, .dk-dock, .dk-menubar, .ql-window, #legend')) return;
    const p = pick(e.clientX, e.clientY);
    if (!p) return;
    e.stopPropagation(); e.preventDefault();
    p.b.body.wakeUp();
    hand = { b: p.b, local: p.local, planeY: clamp(p.height + 0.12, 0.2, 1.3), x: e.clientX, y: e.clientY, pid: e.pointerId };
    hand.target = handTarget(e.clientX, e.clientY);
    sound && sound.scrape(true);
  }, true);
  window.addEventListener('pointermove', (e) => {
    if (!hand || e.pointerId !== hand.pid) return;
    hand.target = handTarget(e.clientX, e.clientY);
  }, true);
  const release = (e) => { if (hand && (!e || e.pointerId === hand.pid)) { hand = null; sound && sound.scrape(false); } };
  window.addEventListener('pointerup', release, true);
  window.addEventListener('pointercancel', release, true);
  window.addEventListener('blur', () => release());

  // double-click a box: the file goes back to the desktop
  window.addEventListener('dblclick', (e) => {
    if (e.target.closest && e.target.closest('.dk-icon, .dk-dock, .dk-menubar, .ql-window, #legend')) return;
    const p = pick(e.clientX, e.clientY);
    if (!p) return;
    desk.returnIcon(p.b.id, e.clientX, e.clientY);
    remove(p.b);
  }, true);

  const q = new THREE.Quaternion(), wp = new THREE.Vector3();
  return {
    boxes,
    /** a desktop icon dropped at (clientX, clientY): true if it became a box */
    drop(icon, clientX, clientY) {
      ghost.visible = false;
      const t = dropTarget(clientX, clientY, icon.bytes);
      if (!t) return false;
      make(icon, t.pos, t.yaw);
      lastBuild = performance.now() / 1000;
      return true;
    },
    get lastBuild() { return lastBuild; },
    setBaitTest(fn) { baitTest = fn; },
    markBuild() { lastBuild = performance.now() / 1000; },
    /**
     * A whole selection dropped at once: it is stacked into a wall where you dropped it, the way you would pile
     * moving boxes into a doorway: the biggest at the bottom, rows ~1 m wide, each row on top of the one below,
     * square to your line of sight. Returns the ids that went in.
     */
    dropMany(icons, clientX, clientY) {
      ghost.visible = false;
      if (!icons.length) return [];
      const biggest = icons.reduce((a, b) => (b.bytes > a.bytes ? b : a));
      const t = dropTarget(clientX, clientY, biggest.bytes);
      if (!t) return [];
      const base = t.pos.clone(); base.y -= t.size.h / 2;          // the surface it lands on
      const toCam = new THREE.Vector3(camera.position.x - base.x, 0, camera.position.z - base.z).normalize();
      const side = new THREE.Vector3(toCam.z, 0, -toCam.x);
      const yaw = Math.atan2(toCam.x, toCam.z);
      const order = [...icons].sort((a, b) => b.bytes - a.bytes);
      // rows up to 2.2 m wide, a layer up to the height of the door head; then the next layer goes in front of it
      const ROW = 2.2, TOP = 1.95;      // rows across the hallway (2.5 m wide)
      const out = [];
      let layer = 0, y = base.y, rowW = 0, row = [], depth = 0;
      const place = () => {
        if (!row.length) return;
        const total = row.reduce((a, e) => a + e.sz.w + 0.02, -0.02);
        let x = -total / 2, tallest = 0;
        for (const { ic, sz } of row) {
          const p = base.clone().addScaledVector(side, x + sz.w / 2).addScaledVector(toCam, layer + sz.d / 2 - t.size.d / 2);
          p.y = y + sz.h / 2 + 0.015;
          p.x = clamp(p.x, ROOM.x0 + sz.w / 2, ROOM.x1 - sz.w / 2);
          // never inside a wall, a jamb or the head of the doorway: step it back into the room until it is clear
          const shape = new RAPIER.Cuboid(sz.w / 2 - 0.01, sz.h / 2 - 0.01, sz.d / 2 - 0.01);
          const rot = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, yaw, 0));
          for (let k = 0; k < 30 && world.intersectionWithShape(p, rot, shape, RAPIER.QueryFilterFlags.EXCLUDE_DYNAMIC | RAPIER.QueryFilterFlags.EXCLUDE_KINEMATIC); k++) {
            p.addScaledVector(toCam, 0.04);
          }
          make(ic, p, yaw);
          out.push(ic.id);
          x += sz.w + 0.02; tallest = Math.max(tallest, sz.h); depth = Math.max(depth, sz.d);
        }
        y += tallest + 0.01;
        row = []; rowW = 0;
      };
      for (const ic of order) {
        const sz = sizeOf(ic.bytes);
        if (row.length && rowW + sz.w > ROW) place();
        if (y + sz.h > base.y + TOP) { place(); layer += depth + 0.03; depth = 0; y = base.y; }
        row.push({ ic, sz }); rowW += sz.w + 0.02;
      }
      place();
      lastBuild = performance.now() / 1000;
      return out;
    },
    dropTarget,
    /** called before every physics step: the hand's force on the grabbed box */
    beforeStep(dt) {
      if (!hand) return;
      lastBuild = performance.now() / 1000;
      const { body } = hand.b;
      const t = body.translation(), r = body.rotation();
      q.set(r.x, r.y, r.z, r.w);
      wp.copy(hand.local).applyQuaternion(q).add(v.set(t.x, t.y, t.z));
      const lv = body.linvel();
      // velocity of the grabbed point ≈ body velocity (ignore spin for damping)
      const fx = HAND_K * (hand.target.x - wp.x) - HAND_C * lv.x;
      const fy = HAND_K * (hand.target.y - wp.y) - HAND_C * lv.y;
      const fz = HAND_K * (hand.target.z - wp.z) - HAND_C * lv.z;
      const f = Math.hypot(fx, fy, fz), k = f > HAND_FORCE ? HAND_FORCE / f : 1;
      body.applyImpulseAtPoint({ x: fx * k * dt, y: fy * k * dt, z: fz * k * dt }, { x: wp.x, y: wp.y, z: wp.z }, true);
    },
    /** push everything near p away (a blow, or the jumpscare) */
    blast(p, impulse, radius) {
      for (const b of boxes.values()) {
        const t = b.body.translation();
        const dx = t.x - p.x, dz = t.z - p.z, d = Math.hypot(dx, dz);
        if (d > radius) continue;
        const k = impulse * (1 - d / radius) / Math.max(d, 0.2);
        b.body.applyImpulse({ x: dx * k, y: impulse * 0.35 * (1 - d / radius), z: dz * k }, true);
        b.body.applyTorqueImpulse({ x: (Math.random() - 0.5) * impulse * 0.05, y: (Math.random() - 0.5) * impulse * 0.05, z: (Math.random() - 0.5) * impulse * 0.05 }, true);
      }
    },
    /** boxes lying beyond the doorway, in the corridor, at rest: bait */
    bait() {
      const out = [];
      for (const b of boxes.values()) {
        if (b.carried) continue;
        const t = b.body.translation();
        if (baitTest(new THREE.Vector3(t.x, 0, t.z)) && b.body.isSleeping()) out.push(b);
      }
      return out;
    },
    /** something picked the box up: it follows the hand it is given until consumed or dropped */
    carry(b) {
      b.carried = true;
      if (hand && hand.b === b) hand = null;
      b.body.setBodyType(RAPIER.RigidBodyType.KinematicPositionBased, true);
      b.collider.setSensor(true);          // held against its chest: it must not shove the one carrying it
    },
    holdAt(b, pos, quat) {
      b.body.setNextKinematicTranslation(pos);
      b.body.setNextKinematicRotation(quat);
    },
    /** dropped (it was startled): falls from where it is */
    letGo(b) {
      b.carried = false;
      b.collider.setSensor(false);
      b.body.setBodyType(RAPIER.RigidBodyType.Dynamic, true);
      b.body.wakeUp();
    },
    /** gone into the dark: the box disappears, the file does not come back (yet) */
    consume(b) { remove(b); },
    /** boxes whose centre is within r of the point (horizontal) */
    near(p, r) {
      const out = [];
      for (const b of boxes.values()) { const t = b.body.translation(); if (Math.hypot(t.x - p.x, t.z - p.z) < r) out.push(b); }
      return out;
    },
    sync() {
      for (const b of boxes.values()) {
        const t = b.body.translation(), r = b.body.rotation();
        b.mesh.position.set(t.x, t.y, t.z);
        b.mesh.quaternion.set(r.x, r.y, r.z, r.w);
        if (t.y < -2) { desk.returnIcon(b.id); remove(b); }   // fell out of the world: give it back
      }
    },
    get holding() { return !!hand; },
  };
}
