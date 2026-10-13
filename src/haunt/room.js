// The static environment: public/models/room.glb (blender/room.py), or a plain placeholder room with the same
// layout when the glb is missing, so the runtime can be worked on without the asset.

import * as THREE from 'three';
import { ROOM, WALL_T, DOOR, CORRIDOR } from './layout.js';

export async function loadRoom(loader, renderer, url = '/models/hallway.glb') {
  let gltf = null;
  try { gltf = await loader.loadAsync(url); }
  catch (err) { console.warn('[haunt] room.glb missing, using the placeholder room:', err && err.message); }
  const root = gltf ? gltf.scene : placeholderRoom();
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  let target = null;
  root.traverse((o) => {
    if (o.name === 'Empty_FlashlightTarget_Default') target = o.getWorldPosition(new THREE.Vector3());
    if (!o.isMesh) return;
    o.castShadow = true;
    o.receiveShadow = true;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'alphaMap']) {
        if (m[k]) m[k].anisotropy = maxAniso;
      }
      if (/outside/i.test(m.name + o.name)) {
        // the night outside the windows: it glows by itself and takes no light or shadow
        o.castShadow = o.receiveShadow = false;
        if (m.emissiveMap) { m.emissiveIntensity = 1; }
      }
      if (m.transparent) {
        // cobwebs, grime decals, bulb glass and shards: blended, no depth writes, no shadows
        m.depthWrite = false;
        o.castShadow = false;
        if (/web/i.test(m.name + o.name)) { m.side = THREE.DoubleSide; m.alphaTest = 0.05; }
        if (/decal|grime/i.test(m.name + o.name)) { m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -2; }
      }
      if (m.aoMap) occludeDirectLight(m);
    }
  });
  return { root, defaultTarget: target || new THREE.Vector3(DOOR.cx + 0.9, 1.3, ROOM.z0) };
}

/**
 * three.js applies aoMap to ambient / indirect light only, and this room has none: the torch is the only light.
 * The shadow map is too coarse for contact shadows in corners and under furniture, so let the baked occlusion
 * also attenuate the torch's diffuse and specular light, partly (it stands in for the missing contact shadows).
 */
function occludeDirectLight(m) {
  m.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace('#include <aomap_fragment>', `#include <aomap_fragment>
      reflectedLight.directDiffuse *= mix(1.0, ambientOcclusion, 0.6);
      reflectedLight.directSpecular *= mix(1.0, ambientOcclusion, 0.6);`);
  };
  m.customProgramCacheKey = () => 'ao-direct';
}

// ------------------------------------------------------------------------------------------- placeholder room
function canvasTex(w, h, draw, srgb = true, repeat = [1, 1]) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat[0], repeat[1]);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function speckle(g, w, h, n, a, col) {
  for (let i = 0; i < n; i++) {
    g.fillStyle = `rgba(${col},${Math.random() * a})`;
    const s = Math.random() * 3 + 0.5;
    g.fillRect(Math.random() * w, Math.random() * h, s, s);
  }
}

function placeholderRoom() {
  const group = new THREE.Group();
  group.name = 'Room';
  const wallTex = canvasTex(512, 512, (g, w, h) => {
    g.fillStyle = '#6b6252'; g.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 32) { g.fillStyle = 'rgba(40,30,20,.18)'; g.fillRect(x, 0, 10, h); }
    speckle(g, w, h, 9000, 0.25, '20,15,10');
    const grd = g.createLinearGradient(0, 0, 0, h); grd.addColorStop(0, 'rgba(30,25,15,.4)'); grd.addColorStop(0.3, 'rgba(0,0,0,0)');
    g.fillStyle = grd; g.fillRect(0, 0, w, h);
  }, true, [4, 1.4]);
  const floorTex = canvasTex(512, 512, (g, w, h) => {
    for (let y = 0; y < h; y += 32) {
      const l = 50 + Math.random() * 25; g.fillStyle = `rgb(${l + 18},${l + 4},${l - 12})`; g.fillRect(0, y, w, 31);
      g.fillStyle = 'rgba(0,0,0,.6)'; g.fillRect(0, y + 31, w, 1);
      const cut = Math.random() * w; g.fillRect(cut, y, 1, 31);
    }
    speckle(g, w, h, 6000, 0.3, '10,8,6');
  }, true, [3, 3]);
  const ceilTex = canvasTex(256, 256, (g, w, h) => { g.fillStyle = '#7a756a'; g.fillRect(0, 0, w, h); speckle(g, w, h, 4000, 0.2, '30,25,20'); }, true, [3, 3]);

  const wall = new THREE.MeshStandardMaterial({ map: wallTex, roughness: 0.92 });
  const floor = new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.75 });
  const ceil = new THREE.MeshStandardMaterial({ map: ceilTex, roughness: 0.95 });
  const trim = new THREE.MeshStandardMaterial({ color: 0x9a948a, roughness: 0.6 });

  const box = (w, h, d, mat, x, y, z, name) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    m.position.set(x, y, z); if (name) m.name = name; group.add(m); return m;
  };
  const W = ROOM.x1 - ROOM.x0, H = ROOM.y1 - ROOM.y0, D = ROOM.z1 - ROOM.z0;
  const cx = (ROOM.x0 + ROOM.x1) / 2, cz = (ROOM.z0 + ROOM.z1) / 2;
  box(W, 0.1, D, floor, cx, -0.05, cz);
  box(W, 0.1, D, ceil, cx, H + 0.05, cz);
  box(0.1, H, D, wall, ROOM.x0 - 0.05, H / 2, cz);
  box(0.1, H, D, wall, ROOM.x1 + 0.05, H / 2, cz);
  box(W, H, 0.1, wall, cx, H / 2, ROOM.z1 + 0.05);
  // back wall with the opening
  const dx0 = DOOR.cx - DOOR.w / 2, dx1 = DOOR.cx + DOOR.w / 2, bz = ROOM.z0 - WALL_T / 2;
  box(dx0 - ROOM.x0, H, WALL_T, wall, (ROOM.x0 + dx0) / 2, H / 2, bz);
  box(ROOM.x1 - dx1, H, WALL_T, wall, (ROOM.x1 + dx1) / 2, H / 2, bz);
  box(DOOR.w, H - DOOR.h, WALL_T, wall, DOOR.cx, (H + DOOR.h) / 2, bz);
  // casing
  box(0.09, DOOR.h + 0.09, 0.03, trim, dx0 - 0.045, (DOOR.h + 0.09) / 2, ROOM.z0 + 0.015);
  box(0.09, DOOR.h + 0.09, 0.03, trim, dx1 + 0.045, (DOOR.h + 0.09) / 2, ROOM.z0 + 0.015);
  box(DOOR.w + 0.18, 0.09, 0.03, trim, DOOR.cx, DOOR.h + 0.045, ROOM.z0 + 0.015);
  // baseboards
  box(W, 0.14, 0.02, trim, cx, 0.07, ROOM.z0 + 0.01);
  // corridor
  const corr = new THREE.Group(); corr.name = 'Corridor'; group.add(corr);
  const CW = CORRIDOR.x1 - CORRIDOR.x0, CH = CORRIDOR.y1, CD = CORRIDOR.z1 - CORRIDOR.z0;
  const ccx = (CORRIDOR.x0 + CORRIDOR.x1) / 2, ccz = (CORRIDOR.z0 + CORRIDOR.z1) / 2;
  const add = (m) => { group.remove(m); corr.add(m); };
  add(box(CW, 0.1, CD, floor, ccx, -0.05, ccz));
  add(box(CW, 0.1, CD, ceil, ccx, CH + 0.05, ccz));
  add(box(CW, CH, 0.1, wall, ccx, CH / 2, CORRIDOR.z0 - 0.05));
  add(box(0.1, CH, CD, wall, CORRIDOR.x0 - 0.05, CH / 2, ccz));
  add(box(0.1, CH, CD, wall, CORRIDOR.x1 + 0.05, CH / 2, ccz));
  // a chair, so shadows have something to do
  const wood = new THREE.MeshStandardMaterial({ color: 0x4a3322, roughness: 0.7 });
  const chair = new THREE.Group(); chair.position.set(1.4, 0, -2.6); chair.rotation.y = 2.6; group.add(chair);
  const leg = (x, z, h) => { const m = new THREE.Mesh(new THREE.BoxGeometry(0.04, h, 0.04), wood); m.position.set(x, h / 2, z); chair.add(m); };
  leg(-0.2, -0.2, 0.45); leg(0.2, -0.2, 0.45); leg(-0.2, 0.2, 0.95); leg(0.2, 0.2, 0.95);
  const seat = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.04, 0.46), wood); seat.position.y = 0.46; chair.add(seat);
  for (let i = 0; i < 3; i++) { const s = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.05, 0.02), wood); s.position.set(0, 0.6 + i * 0.13, 0.2); chair.add(s); }
  return group;
}
