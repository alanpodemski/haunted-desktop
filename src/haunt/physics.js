// Rigid-body world (Rapier 3D): the room's shell and big furniture as static colliders, the file boxes as dynamic
// bodies, the creature as a capsule. Fixed 1/120 s steps, so contacts are stable at 30 and at 60 fps.

import RAPIER from '@dimforge/rapier3d-compat';
import * as THREE from 'three';
import { ROOM, WALL_T, DOOR, CORRIDOR } from './layout.js';

const STEP = 1 / 120;

export async function createPhysics(roomRoot) {
  await RAPIER.init();
  const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  world.timestep = STEP;
  const events = new RAPIER.EventQueue(true);

  // ---- static shell
  const fixed = (hx, hy, hz, x, y, z, friction = 0.5, rot = null) => {
    const desc = RAPIER.RigidBodyDesc.fixed().setTranslation(x, y, z);
    if (rot) desc.setRotation(rot);
    const body = world.createRigidBody(desc);
    world.createCollider(RAPIER.ColliderDesc.cuboid(hx, hy, hz).setFriction(friction), body);
  };
  // An environment that brings its own collision boxes (a `Colliders` node with COL_* meshes) uses those; the v1
  // room is described here by hand.
  roomRoot.updateMatrixWorld(true);
  const authored = roomRoot.getObjectByName('Colliders');
  if (authored) {
    const p = new THREE.Vector3(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), c = new THREE.Vector3(), sz = new THREE.Vector3();
    authored.traverse((o) => {
      if (!o.isMesh) return;
      o.visible = false;
      o.geometry.computeBoundingBox();
      o.geometry.boundingBox.getCenter(c); o.geometry.boundingBox.getSize(sz);
      o.matrixWorld.decompose(p, q, sc);
      c.multiply(sc).applyQuaternion(q).add(p);
      const fr = /floor|carpet/i.test(o.name) ? 0.45 : 0.55;
      fixed(Math.max(0.005, Math.abs(sz.x * sc.x) / 2), Math.max(0.005, Math.abs(sz.y * sc.y) / 2), Math.max(0.005, Math.abs(sz.z * sc.z) / 2),
        c.x, c.y, c.z, fr, { x: q.x, y: q.y, z: q.z, w: q.w });
    });
  } else buildV1Room();
  function buildV1Room() {
  const T = 0.25; // collider thickness behind each surface
  // room
  const rcx = (ROOM.x0 + ROOM.x1) / 2, rcz = (ROOM.z0 + ROOM.z1) / 2;
  const rhx = (ROOM.x1 - ROOM.x0) / 2, rhz = (ROOM.z1 - ROOM.z0) / 2, rhy = ROOM.y1 / 2;
  fixed(rhx + T, T, rhz + T, rcx, -T, rcz, 0.45);                          // floorboards
  fixed(rhx + T, T, rhz + T, rcx, ROOM.y1 + T, rcz);                       // ceiling
  fixed(T, rhy, rhz + T, ROOM.x0 - T, rhy, rcz);                           // left wall
  fixed(T, rhy, rhz + T, ROOM.x1 + T, rhy, rcz);                           // right wall
  fixed(rhx + T, rhy, T, rcx, rhy, ROOM.z1 + T);                           // wall behind the camera
  // back wall, around the opening
  const dx0 = DOOR.cx - DOOR.w / 2, dx1 = DOOR.cx + DOOR.w / 2, bz = ROOM.z0 - WALL_T / 2;
  fixed((dx0 - ROOM.x0) / 2 + T, rhy, WALL_T / 2, (ROOM.x0 + dx0) / 2 - T / 2, rhy, bz);
  fixed((ROOM.x1 - dx1) / 2 + T, rhy, WALL_T / 2, (ROOM.x1 + dx1) / 2 + T / 2, rhy, bz);
  fixed(DOOR.w / 2, (ROOM.y1 - DOOR.h) / 2, WALL_T / 2, DOOR.cx, (ROOM.y1 + DOOR.h) / 2, bz);
  // corridor
  const ccx = (CORRIDOR.x0 + CORRIDOR.x1) / 2, ccz = (CORRIDOR.z0 + CORRIDOR.z1) / 2;
  const chx = (CORRIDOR.x1 - CORRIDOR.x0) / 2, chz = (CORRIDOR.z1 - CORRIDOR.z0) / 2, chy = CORRIDOR.y1 / 2;
  fixed(chx + T, T, chz + T, ccx, -T, ccz, 0.45);
  fixed(chx + T, T, chz + T, ccx, CORRIDOR.y1 + T, ccz);
  fixed(chx + T, chy, T, ccx, chy, CORRIDOR.z0 - T);
  fixed(T, chy, chz + T, CORRIDOR.x0 - T, chy, ccz);
  fixed(T, chy, chz + T, CORRIDOR.x1 + T, chy, ccz);

  // ---- furniture: axis-aligned boxes around the big props of room.glb
  const box = new THREE.Box3();
  roomRoot.traverse((o) => {
    if (!/^(Bed_IronFrame|Bed_Mattress|Dresser|Chair_FacingWall|Radiator)$/.test(o.name)) return;
    box.setFromObject(o);
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    fixed(s.x / 2, s.y / 2, s.z / 2, c.x, c.y, c.z, 0.6);
  });
  }

  let acc = 0;
  const contactCbs = [];
  const api = {
    RAPIER, world,
    creatureBody: null,
    /** first solid thing along a ray (the creature's capsule excluded): { point, normal, dist } */
    cast(o, d, maxDist = 30) {
      const hit = world.castRayAndGetNormal(new RAPIER.Ray({ x: o[0], y: o[1], z: o[2] }, { x: d[0], y: d[1], z: d[2] }), maxDist, true,
        undefined, undefined, undefined, api.creatureBody || undefined);
      const t = hit ? hit.timeOfImpact : maxDist;
      const n = hit ? hit.normal : { x: -d[0], y: -d[1], z: -d[2] };
      return { point: [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t], normal: [n.x, n.y, n.z], dist: t };
    },
    onContactForce(cb) { contactCbs.push(cb); },
    step(dt, beforeStep) {
      acc += Math.min(dt, 0.1);
      let n = 0;
      while (acc >= STEP && n < 12) {
        if (beforeStep) beforeStep(STEP);
        world.step(events);
        acc -= STEP; n++;
      }
      events.drainContactForceEvents((e) => {
        for (const cb of contactCbs) cb(e);
      });
      return n;
    },
    STEP,
  };
  return api;
}
