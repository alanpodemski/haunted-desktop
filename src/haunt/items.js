// Things to defend yourself with: the .usdz files on the desktop. Dropped into the room each becomes a real object
// with its own physics and behaviour. Their desktop icons are 3D thumbnails of the same models (Finder shows .usdz
// files that way), rendered here once at start.
//
//   candle      a 1.5 cd flame: a small pool of light it will not move in. Burns ~2 min, goes out if knocked over.
//   road_flare  a red magnesium flare, ~25 cd for 30 s, with sparks: it freezes anywhere near it.
//   salt        poured out as a line across its path; it will not step over it until it has worn it away.
//   batteries   two fresh cells for the torch (the old ones drop on the floor).
//   music_box   it plays; it goes to listen, and then it breaks it. Bait that buys time anywhere.

import * as THREE from 'three';

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const ITEM_TYPES = ['candle', 'road_flare', 'salt', 'batteries', 'music_box'];
export function itemType(name) {
  const n = (name || '').toLowerCase();
  if (!n.endsWith('.usdz')) return null;
  return ITEM_TYPES.find((t) => n.startsWith(t)) || null;
}

// ------------------------------------------------------------------------------------------------ models
function canvasTex(w, h, draw) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  return t;
}

/** a church candle: wax with drips, a charred wick */
function candleModel() {
  const g = new THREE.Group();
  const prof = [];
  for (let i = 0; i <= 12; i++) {
    const y = i / 12 * 0.14;
    prof.push(new THREE.Vector2(0.024 + 0.002 * Math.sin(i * 2.1) + (i > 10 ? -(i - 10) * 0.004 : 0), y));
  }
  prof.unshift(new THREE.Vector2(0, 0)); prof.push(new THREE.Vector2(0.012, 0.142), new THREE.Vector2(0, 0.138));
  const wax = new THREE.MeshPhysicalMaterial({ color: 0xece2cc, roughness: 0.55, transmission: 0.0, sheen: 0.3, sheenColor: 0xffe7c0 });
  const body = new THREE.Mesh(new THREE.LatheGeometry(prof, 24), wax);
  body.castShadow = body.receiveShadow = true; g.add(body);
  // drips
  for (let i = 0; i < 5; i++) {
    const a = Math.random() * Math.PI * 2, len = 0.02 + Math.random() * 0.05;
    const d = new THREE.Mesh(new THREE.CapsuleGeometry(0.004, len, 3, 6), wax);
    d.position.set(Math.cos(a) * 0.025, 0.14 - len / 2 - 0.004, Math.sin(a) * 0.025);
    g.add(d);
  }
  const wick = new THREE.Mesh(new THREE.CylinderGeometry(0.0012, 0.0012, 0.012, 5), new THREE.MeshStandardMaterial({ color: 0x111111 }));
  wick.position.y = 0.146; g.add(wick);
  g.userData.flameY = 0.162;
  return { group: g, shape: { kind: 'cyl', r: 0.026, h: 0.14, mass: 0.18 } };
}

/** a road flare: red paper tube, striker cap */
function flareModel() {
  const g = new THREE.Group();
  const paper = new THREE.MeshStandardMaterial({
    map: canvasTex(256, 64, (c, w, h) => {
      c.fillStyle = '#b3151a'; c.fillRect(0, 0, w, h);
      c.fillStyle = 'rgba(255,255,255,.85)'; c.font = '700 26px Helvetica, Arial'; c.fillText('FLARE  15 MIN', 30, 42);
      for (let i = 0; i < 400; i++) { c.fillStyle = `rgba(0,0,0,${Math.random() * 0.1})`; c.fillRect(Math.random() * w, Math.random() * h, 2, 1); }
    }), roughness: 0.7,
  });
  const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 0.22, 16), paper);
  tube.rotation.z = Math.PI / 2; tube.castShadow = tube.receiveShadow = true; g.add(tube);
  const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.017, 0.017, 0.03, 16), new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.6 }));
  cap.rotation.z = Math.PI / 2; cap.position.x = -0.12; g.add(cap);
  g.userData.flameX = 0.115;
  return { group: g, shape: { kind: 'cylX', r: 0.017, h: 0.25, mass: 0.2 } };
}

/** a round cardboard salt canister */
function saltModel() {
  const g = new THREE.Group();
  const label = new THREE.MeshStandardMaterial({
    map: canvasTex(512, 128, (c, w, h) => {
      c.fillStyle = '#1f4fa8'; c.fillRect(0, 0, w, h);
      c.fillStyle = '#f2f2f2'; c.font = '900 64px Georgia, serif'; c.fillText('SALT', 170, 84);
      c.fillStyle = 'rgba(255,255,255,.7)'; c.font = '600 18px Helvetica'; c.fillText('IODIZED · 26 OZ', 190, 112);
      for (let i = 0; i < 900; i++) { c.fillStyle = `rgba(0,0,0,${Math.random() * 0.12})`; c.fillRect(Math.random() * w, Math.random() * h, 2, 2); }
    }), roughness: 0.75,
  });
  const top = new THREE.MeshStandardMaterial({ color: 0xd8d8d0, roughness: 0.6 });
  const can = new THREE.Mesh(new THREE.CylinderGeometry(0.043, 0.043, 0.135, 28), [label, top, top]);
  can.position.y = 0.0675; can.castShadow = can.receiveShadow = true; g.add(can);
  const spout = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.003, 0.012), new THREE.MeshStandardMaterial({ color: 0xbfbfbf, metalness: 0.6, roughness: 0.4 }));
  spout.position.set(0.02, 0.137, 0); g.add(spout);
  return { group: g, shape: { kind: 'cyl', r: 0.043, h: 0.135, mass: 0.75 } };
}

/** two D cells */
function batteriesModel() {
  const g = new THREE.Group();
  for (let i = 0; i < 2; i++) {
    const cell = new THREE.Group();
    const jacket = new THREE.Mesh(new THREE.CylinderGeometry(0.017, 0.017, 0.061, 20), new THREE.MeshStandardMaterial({
      map: canvasTex(256, 64, (c, w, h) => {
        const gr = c.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, '#1a1a1a'); gr.addColorStop(0.5, '#3a3a3a'); gr.addColorStop(1, '#141414');
        c.fillStyle = gr; c.fillRect(0, 0, w, h);
        c.fillStyle = '#d4a017'; c.fillRect(0, 0, w, 14);
        c.fillStyle = '#e8e8e8'; c.font = '700 22px Helvetica'; c.fillText('ALKALINE  D  1.5V', 20, 44);
      }), roughness: 0.35, metalness: 0.3,
    }));
    jacket.castShadow = jacket.receiveShadow = true; cell.add(jacket);
    const nub = new THREE.Mesh(new THREE.CylinderGeometry(0.0045, 0.0045, 0.0035, 12), new THREE.MeshStandardMaterial({ color: 0xc8c8c8, metalness: 1, roughness: 0.25 }));
    nub.position.y = 0.032; cell.add(nub);
    cell.rotation.z = Math.PI / 2; cell.position.set(0, 0.017, (i - 0.5) * 0.036);
    g.add(cell);
  }
  return { group: g, shape: { kind: 'box', w: 0.066, h: 0.034, d: 0.07, mass: 0.28 } };
}

/** a small walnut music box with a brass crank and a dancer */
function musicBoxModel() {
  const g = new THREE.Group();
  const wood = new THREE.MeshStandardMaterial({
    map: canvasTex(256, 256, (c, w, h) => {
      c.fillStyle = '#5a3418'; c.fillRect(0, 0, w, h);
      for (let y = 0; y < h; y += 3) { c.fillStyle = `rgba(${Math.random() < 0.5 ? '30,15,5' : '120,70,35'},${0.15 + Math.random() * 0.2})`; c.fillRect(0, y + Math.sin(y * 0.2) * 2, w, 1.5); }
    }), roughness: 0.38,
  });
  const brass = new THREE.MeshStandardMaterial({ color: 0xc8a050, metalness: 1, roughness: 0.3 });
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.07, 0.085), wood);
  box.position.y = 0.035; box.castShadow = box.receiveShadow = true; g.add(box);
  const lid = new THREE.Mesh(new THREE.BoxGeometry(0.124, 0.012, 0.089), wood);
  lid.position.set(0, 0.075, -0.044); lid.geometry.translate(0, 0, 0.044); lid.rotation.x = -1.1; g.add(lid);
  const crank = new THREE.Mesh(new THREE.TorusGeometry(0.01, 0.0018, 6, 12, Math.PI * 1.5), brass);
  crank.position.set(0.064, 0.035, 0); crank.rotation.y = Math.PI / 2; g.add(crank);
  const dancer = new THREE.Mesh(new THREE.ConeGeometry(0.008, 0.035, 10), new THREE.MeshStandardMaterial({ color: 0xf0e4e0, roughness: 0.4 }));
  dancer.position.set(0, 0.09, 0); g.add(dancer);
  g.userData.dancer = dancer;
  return { group: g, shape: { kind: 'box', w: 0.12, h: 0.07, d: 0.085, mass: 0.45 } };
}

const MODELS = { candle: candleModel, road_flare: flareModel, salt: saltModel, batteries: batteriesModel, music_box: musicBoxModel };

// ------------------------------------------------------------------------------------------------ icons
/** Finder-style .usdz thumbnails: the object alone on transparent, three-quarter view, soft studio light */
export function renderItemIcons() {
  const out = {};
  const r = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  r.setSize(256, 256, false);
  r.outputColorSpace = THREE.SRGBColorSpace;
  r.toneMapping = THREE.ACESFilmicToneMapping;
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x404040, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(1, 2, 1.5); scene.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 1.0); rim.position.set(-1.5, 1, -1); scene.add(rim);
  const cam = new THREE.PerspectiveCamera(30, 1, 0.01, 10);
  for (const t of ITEM_TYPES) {
    const { group } = MODELS[t]();
    if (t === 'road_flare') group.rotation.set(0, 0.6, 0.5);
    scene.add(group);
    const box = new THREE.Box3().setFromObject(group);
    const c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length();
    cam.position.copy(c).add(new THREE.Vector3(0.75, 0.55, 1).normalize().multiplyScalar(size * 1.75));
    cam.lookAt(c);
    r.render(scene, cam);
    out[t] = r.domElement.toDataURL('image/png');
    scene.remove(group);
  }
  r.dispose();
  return out;
}

// ------------------------------------------------------------------------------------------------ in the room
export function createItems({ scene, physics, boxes, flashlight, sound, desk }) {
  const { RAPIER, world } = physics;
  const live = [];             // { type, icon, group, body, collider, ... }
  const saltLines = [];        // { a: Vector3, b: Vector3, strength 0..1, mesh }
  const tmp = new THREE.Vector3();

  function addBody(obj, shape, pos, yaw) {
    const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, yaw, 0));
    const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic().setTranslation(pos.x, pos.y, pos.z).setRotation(q)
      .setLinearDamping(0.1).setAngularDamping(0.4).setCcdEnabled(true));
    let desc;
    if (shape.kind === 'cyl') desc = RAPIER.ColliderDesc.cylinder(shape.h / 2, shape.r).setTranslation(0, shape.h / 2, 0);
    else if (shape.kind === 'cylX') desc = RAPIER.ColliderDesc.cylinder(shape.h / 2, shape.r).setRotation(new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, Math.PI / 2)));
    else desc = RAPIER.ColliderDesc.cuboid(shape.w / 2, shape.h / 2, shape.d / 2).setTranslation(0, shape.h / 2, 0);
    const collider = world.createCollider(desc.setMass(shape.mass).setFriction(0.6).setRestitution(0.1), body);
    obj.body = body; obj.collider = collider;
  }

  // ---- a flame: an additive billboard whose shape flickers, and the light it gives
  const flameMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(1, 0.62, 0.25) }, uGain: { value: 1 } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; vec4 mv = modelViewMatrix * vec4(0.,0.,0.,1.); mv.xy += position.xy; gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform float uTime; uniform vec3 uColor; uniform float uGain; varying vec2 vUv;
      void main(){ vec2 p = vUv - vec2(0.5, 0.25); float sway = 0.05 * sin(uTime * 9.0 + p.y * 6.0) * p.y * 2.0;
        p.x += sway; float r = length(vec2(p.x * 2.6, max(p.y, 0.0) * 1.0 + min(p.y, 0.0) * 2.4));
        float a = smoothstep(0.42, 0.0, r); float core = smoothstep(0.18, 0.0, r);
        gl_FragColor = vec4((uColor * a + vec3(1.0, 0.95, 0.85) * core) * uGain, 1.0); }`,
  });
  function flame(size, color) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size * 1.6), flameMat.clone());
    m.material.uniforms.uColor.value = new THREE.Color(color);
    m.frustumCulled = false;
    return m;
  }

  // sparks for the flare
  function sparks() {
    const n = 120;
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(n * 3), vel = new Float32Array(n * 3), life = new Float32Array(n);
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xffa070, size: 0.012, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    pts.frustumCulled = false;
    return { pts, pos, vel, life, n };
  }

  function make(type, icon, at, yaw) {
    const { group, shape } = MODELS[type]();
    scene.add(group);
    const it = { type, icon, group, shape, age: 0, lit: false, done: false };
    if (type === 'road_flare') at.y = Math.max(at.y, 0.05);
    addBody(it, shape, at, yaw);
    if (type === 'candle') {
      it.flame = flame(0.03, 0xff9a40); scene.add(it.flame);
      it.light = new THREE.PointLight(0xffa24a, 0, 0, 2); scene.add(it.light);
      it.lit = true; it.burn = 120; it.cd = 1.5;
      sound && sound.match();
    } else if (type === 'road_flare') {
      it.flame = flame(0.07, 0xff3020); scene.add(it.flame);
      it.light = new THREE.PointLight(0xff3a24, 0, 0, 2);
      // a flare is the one light strong enough to throw hard shadows across the room
      it.light.castShadow = true; it.light.shadow.mapSize.set(512, 512);
      it.light.shadow.bias = -0.002; it.light.shadow.normalBias = 0.03; it.light.shadow.camera.near = 0.05; it.light.shadow.camera.far = 9;
      scene.add(it.light);
      it.sp = sparks(); scene.add(it.sp.pts);
      it.lit = true; it.burn = 30; it.cd = 25;
      it.hiss = sound && sound.flareHiss();
    } else if (type === 'music_box') {
      it.playing = true; it.tune = sound && sound.musicBox();
      it.hp = 1;
    }
    live.push(it);
    return it;
  }

  function pourSalt(at) {
    // a line across the way it would come: perpendicular to the doorway → camera direction at this point
    const dir = new THREE.Vector3(0.25 - at.x, 0, 0.35 - at.z).normalize();
    const side = new THREE.Vector3(-dir.z, 0, dir.x);
    const half = 0.6;
    const a = at.clone().addScaledVector(side, -half), b = at.clone().addScaledVector(side, half);
    a.y = b.y = 0.002;
    // grains: a thin, uneven white strip
    const n = 1400, geo = new THREE.BufferGeometry(), pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const u = Math.random(), spread = (Math.random() + Math.random() - 1) * 0.035 * (1 + 0.5 * Math.sin(u * 17));
      const p = a.clone().lerp(b, u).addScaledVector(dir, spread);
      pos.set([p.x, 0.003 + Math.random() * 0.004, p.z], i * 3);
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mesh = new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xeeeae2, size: 0.007, sizeAttenuation: true }));
    scene.add(mesh);
    saltLines.push({ a, b, strength: 1, mesh });
    sound && sound.pour();
  }

  function remove(it) {
    it.done = true;
    scene.remove(it.group);
    if (it.flame) scene.remove(it.flame);
    if (it.light) scene.remove(it.light);
    if (it.sp) scene.remove(it.sp.pts);
    if (it.hiss) it.hiss.stop();
    if (it.tune) it.tune.stop();
    world.removeRigidBody(it.body);
    const i = live.indexOf(it); if (i >= 0) live.splice(i, 1);
  }

  const up = new THREE.Vector3(0, 1, 0), q = new THREE.Quaternion();
  return {
    live, saltLines,
    /** a .usdz icon dropped at the cursor: true if it was used */
    drop(icon, clientX, clientY) {
      const type = itemType(icon.name);
      if (!type) return false;
      if (type === 'batteries') {
        flashlight.replaceBatteries();
        sound && sound.click(true);
        // the old cells fall out onto the floor at your feet
        const t = boxes.dropTarget(clientX, clientY, 0);
        make('batteries', icon, t ? t.pos : new THREE.Vector3(0.3, 0.4, -0.6), Math.random() * 3);
        return true;
      }
      const t = boxes.dropTarget(clientX, clientY, 0);
      if (!t) return false;
      if (type === 'salt') {
        const floor = t.pos.clone(); floor.y = 0;
        if (t.pos.y > 0.4) return false;          // salt goes on the floor
        pourSalt(floor);
        make('salt', icon, t.pos.clone().add(new THREE.Vector3(0.15, 0.02, 0.1)), 0.4);   // the empty canister
        return true;
      }
      make(type, icon, t.pos.clone(), t.yaw ?? Math.random() * 6);
      return true;
    },
    /** total light from flames at a point, in the same units as flashlight.exposure (≈ lit when > 0.2) */
    lightAt(p) {
      let e = 0;
      for (const it of live) {
        if (!it.lit || !it.light) continue;
        const d2 = Math.max(0.05, it.light.position.distanceToSquared(p));
        e += it.light.intensity / d2 * 0.18;
      }
      return e;
    },
    /** a music box playing somewhere: where it is (the creature goes to it), or null */
    lure() {
      const m = live.find((it) => it.type === 'music_box' && it.playing);
      if (!m) return null;
      const t = m.body.translation();
      return { item: m, pos: new THREE.Vector3(t.x, 0, t.z) };
    },
    /** it broke the music box */
    smash(m) {
      m.playing = false;
      if (m.tune) { m.tune.stop(); m.tune = null; }
      sound && sound.smash(m.group.position);
      m.body.applyImpulse({ x: (Math.random() - 0.5) * 0.6, y: 0.8, z: (Math.random() - 0.5) * 0.6 }, true);
      m.body.applyTorqueImpulse({ x: 0.02, y: 0.03, z: -0.02 }, true);
      setTimeout(() => remove(m), 6000);
    },
    /** would a step from a to b cross an intact salt line? returns the line, or null */
    saltBetween(a, b) {
      for (const s of saltLines) {
        if (s.strength <= 0) continue;
        // segment intersection in the floor plane, with a little reach for its feet
        const d1x = b.x - a.x, d1z = b.z - a.z, d2x = s.b.x - s.a.x, d2z = s.b.z - s.a.z;
        const den = d1x * d2z - d1z * d2x;
        if (Math.abs(den) < 1e-6) continue;
        const ex = s.a.x - a.x, ez = s.a.z - a.z;
        const t = (ex * d2z - ez * d2x) / den, u = (ex * d1z - ez * d1x) / den;
        if (t >= 0 && t <= 1 && u >= -0.15 && u <= 1.15) return s;
      }
      return null;
    },
    /** it scuffs at the line: it wears away over ~12 s of trying */
    wearSalt(s, dt) {
      s.strength = Math.max(0, s.strength - dt / 12);
      s.mesh.material.opacity = 0.3 + 0.7 * s.strength;
      s.mesh.material.transparent = true;
      if (s.strength <= 0) { scene.remove(s.mesh); saltLines.splice(saltLines.indexOf(s), 1); }
    },
    update(dt, time) {
      for (const it of [...live]) {
        it.age += dt;
        const t = it.body.translation(), r = it.body.rotation();
        it.group.position.set(t.x, t.y, t.z);
        it.group.quaternion.set(r.x, r.y, r.z, r.w);
        if (t.y < -2) { remove(it); continue; }
        if (it.type === 'candle' || it.type === 'road_flare') {
          // where the flame is, in world space
          if (it.type === 'candle') tmp.set(0, it.group.userData.flameY * (0.35 + 0.65 * it.burn / 120), 0);
          else tmp.set(it.group.userData.flameX, 0, 0);
          tmp.applyQuaternion(it.group.quaternion).add(it.group.position);
          // a candle knocked over goes out; a flare burns on its side anyway
          up.set(0, 1, 0).applyQuaternion(it.group.quaternion);
          if (it.type === 'candle' && it.lit && up.y < 0.5) { it.lit = false; sound && sound.puff(tmp); }
          if (it.lit) {
            it.burn -= dt;
            if (it.burn <= 0) { it.lit = false; if (it.type === 'road_flare') it.hiss && it.hiss.stop(); }
          }
          // flame physics, roughly: a candle flickers slowly with drafts, a flare sputters fast
          const n = it.type === 'candle'
            ? 0.85 + 0.1 * Math.sin(time * 7.3 + it.age) + 0.06 * Math.sin(time * 17.1) + (Math.random() < 0.01 ? -0.3 : 0)
            : 0.75 + 0.25 * Math.random();
          const on = it.lit ? 1 : 0;
          it.light.intensity = it.cd * n * on * (it.type === 'road_flare' ? clamp(it.burn / 3, 0, 1) : clamp(it.burn / 8, 0.2, 1));
          it.light.position.copy(tmp);
          it.flame.position.copy(tmp);
          it.flame.visible = it.lit;
          it.flame.material.uniforms.uTime.value = time;
          it.flame.material.uniforms.uGain.value = n;
          if (it.type === 'candle') {
            it.group.scale.y = 0.35 + 0.65 * Math.max(0, it.burn) / 120;
            if (!it.lit && it.burn <= 0 && it.age > 125) { remove(it); continue; }
          }
          if (it.sp) {
            const s = it.sp;
            for (let i = 0; i < s.n; i++) {
              s.life[i] -= dt;
              if (s.life[i] <= 0 && it.lit) {
                s.life[i] = 0.3 + Math.random() * 0.6;
                s.pos.set([tmp.x, tmp.y, tmp.z], i * 3);
                s.vel.set([(Math.random() - 0.5) * 1.6, 0.6 + Math.random() * 1.6, (Math.random() - 0.5) * 1.6], i * 3);
              } else if (s.life[i] > 0) {
                s.vel[i * 3 + 1] -= 9.81 * dt;
                for (let k = 0; k < 3; k++) s.pos[i * 3 + k] += s.vel[i * 3 + k] * dt;
                if (s.pos[i * 3 + 1] < 0.005) { s.pos[i * 3 + 1] = 0.005; s.vel[i * 3 + 1] *= -0.3; s.vel[i * 3] *= 0.5; s.vel[i * 3 + 2] *= 0.5; }
              } else s.pos[i * 3 + 1] = -10;
            }
            s.pts.geometry.attributes.position.needsUpdate = true;
            if (!it.lit && it.age > 40) { remove(it); continue; }
          }
        } else if (it.type === 'music_box' && it.playing) {
          it.group.userData.dancer.rotation.y += dt * 2.4;
          if (it.tune) it.tune.setPos(it.group.position);
          if (it.age > 45) { it.playing = false; it.tune && it.tune.stop(); }   // wound down
        } else if (it.type === 'batteries' || it.type === 'salt') {
          if (it.age > 60) { remove(it); continue; }        // spent things fade into the mess
        }
        void q;
      }
    },
  };
}
