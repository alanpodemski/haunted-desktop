// Sanity-check public/models/hallway.glb: required nodes, empties (glTF space), materials, maps, sizes.
//   node blender/check_hallway.mjs
import { readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const path = join(root, 'public', 'models', 'hallway.glb');
const buf = readFileSync(path);
const jl = buf.readUInt32LE(12);
const j = JSON.parse(buf.subarray(20, 20 + jl).toString('utf8'));
const size = statSync(path).size;
console.log(`hallway.glb ${(size / 1e6).toFixed(2)} MB; extensionsUsed: ${(j.extensionsUsed || []).join(', ')}`);
const ids = ['L1', 'L2', 'L3', 'R1', 'R2', 'R3'];
const REQUIRED = ['Hallway', ...ids.map((i) => `SideRoom_${i}`), ...ids.map((i) => `Door_${i}`), ...ids.map((i) => `Inside_${i}`),
  ...ids.map((i) => `Window_${i}`), 'Window_End', 'Empty_FlashlightTarget_Default', 'Outside', 'Colliders'];
const names = j.nodes.map((n) => n.name);
let ok = true;
for (const r of REQUIRED) if (!names.includes(r)) { ok = false; console.log('MISSING node', r); }

// rotate vector v by quaternion q = [x, y, z, w]
const rot = (q, v) => {
  const [x, y, z, w] = q;
  const [vx, vy, vz] = v;
  const tx = 2 * (y * vz - z * vy), ty = 2 * (z * vx - x * vz), tz = 2 * (x * vy - y * vx);
  return [vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)];
};
const f3 = (a) => a.map((v) => (Math.abs(v) < 5e-4 ? 0 : v).toFixed(3)).join(', ');
console.log('empties (glTF space):');
for (const n of j.nodes) {
  if (n.mesh !== undefined || !/^(Door_|Inside_|Window_|Empty_)/.test(n.name)) continue;
  const q = n.rotation || [0, 0, 0, 1];
  console.log(`  ${n.name.padEnd(32)} t=(${f3(n.translation || [0, 0, 0])})  +Z=(${f3(rot(q, [0, 0, 1]))})  -Z=(${f3(rot(q, [0, 0, -1]))})`);
}
console.log('door leaves:');
for (const n of j.nodes) {
  if (!/^DoorLeaf_/.test(n.name)) continue;
  const q = n.rotation || [0, 0, 0, 1];
  const yaw = (2 * Math.atan2(q[1], q[3]) * 180) / Math.PI;
  console.log(`  ${n.name.padEnd(14)} hinge=(${f3(n.translation)}) yawY=${yaw.toFixed(1)} extras=${JSON.stringify(n.extras || {})} leaf+X=(${f3(rot(q, [1, 0, 0]))})`);
}
const col = j.nodes.find((n) => n.name === 'Colliders');
console.log(`colliders: ${col?.children?.length || 0}`);
for (const ci of col?.children || []) {
  const n = j.nodes[ci];
  const acc = j.accessors[j.meshes[n.mesh].primitives[0].attributes.POSITION];
  const ext = acc.max.map((v, i) => v - acc.min[i]);
  const q = n.rotation || [0, 0, 0, 1];
  const yaw = (2 * Math.atan2(q[1], q[3]) * 180) / Math.PI;
  console.log(`  ${n.name.padEnd(30)} c=(${f3(n.translation || [0, 0, 0])}) size=(${f3(ext)}) yawY=${yaw.toFixed(1)}`);
}
console.log('mesh nodes:');
for (const n of j.nodes) {
  if (n.mesh === undefined || n.name.startsWith('COL_')) continue;
  const m = j.meshes[n.mesh];
  const info = m.primitives.map((p) => `${j.materials[p.material]?.name}[${Object.keys(p.attributes).join('/')}]`).join(' ');
  console.log(`  ${n.name.padEnd(28)} ${info}`);
}
const tex = (ti) => (ti === undefined ? null : j.textures[ti.index]);
const imgOf = (ti) => { const t = tex(ti); return t ? `${j.images[t.source].name}` : '-'; };
console.log('materials:');
const NOMAPS = ['Brass', 'Bakelite', 'Cord_Fabric', 'Glass_Milk', 'Glass_Shard', 'Cobweb', 'Decal_Grime'];
for (const m of j.materials) {
  const p = m.pbrMetallicRoughness || {};
  const occ = m.occlusionTexture ? `${imgOf(m.occlusionTexture)} uv${m.occlusionTexture.texCoord || 0}` : '-';
  const em = m.emissiveTexture ? ` emissive=${imgOf(m.emissiveTexture)}` : '';
  console.log(`  ${m.name.padEnd(16)} base=${imgOf(p.baseColorTexture)} mr=${imgOf(p.metallicRoughnessTexture)} normal=${imgOf(m.normalTexture)} occ=${occ} alpha=${m.alphaMode || 'OPAQUE'}${m.alphaCutoff !== undefined ? '@' + m.alphaCutoff : ''} double=${!!m.doubleSided}${em}`);
  if (!NOMAPS.includes(m.name) && m.name !== 'Outside_Night' && !(m.normalTexture && p.baseColorTexture && p.metallicRoughnessTexture)) { ok = false; console.log('    ^ missing a map'); }
  if (m.alphaMode !== 'BLEND' && m.alphaMode !== 'MASK' && !['Outside_Night', ...NOMAPS].includes(m.name) && !m.occlusionTexture) { ok = false; console.log('    ^ no AO'); }
}
let tot = 0;
console.log('images:');
for (let i = 0; i < j.images.length; i++) {
  const b = j.bufferViews[j.images[i].bufferView].byteLength;
  tot += b;
  console.log(`  ${j.images[i].name.padEnd(22)} ${j.images[i].mimeType} ${(b / 1e6).toFixed(2)} MB`);
}
console.log(`texture total ${(tot / 1e6).toFixed(2)} MB; nodes ${j.nodes.length}; meshes ${j.meshes.length}; materials ${j.materials.length}`);
if (size > 30e6) { ok = false; console.log('TOO LARGE'); }
console.log(ok ? 'OK' : 'PROBLEMS');
process.exit(ok ? 0 : 1);
