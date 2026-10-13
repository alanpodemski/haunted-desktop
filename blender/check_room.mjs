// Sanity-check public/models/room.glb: nodes, materials, maps, image sizes.
//   node blender/check_room.mjs
import { readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const path = join(root, 'public', 'models', 'room.glb');
const buf = readFileSync(path);
const jl = buf.readUInt32LE(12);
const j = JSON.parse(buf.subarray(20, 20 + jl).toString('utf8'));
const size = statSync(path).size;
console.log(`room.glb ${(size / 1e6).toFixed(2)} MB; extensionsUsed: ${(j.extensionsUsed || []).join(', ')}`);
const REQUIRED = ['Room', 'Corridor', 'Empty_FlashlightTarget_Default'];
const names = j.nodes.map((n) => n.name);
let ok = true;
for (const r of REQUIRED) if (!names.includes(r)) { ok = false; console.log('MISSING node', r); }
for (const n of j.nodes) {
  const t = (n.translation || [0, 0, 0]).map((v) => v.toFixed(3)).join(', ');
  let info = '';
  if (n.mesh !== undefined) {
    const m = j.meshes[n.mesh];
    info = m.primitives.map((p) => `${j.materials[p.material]?.name}[${Object.keys(p.attributes).join('/')}]`).join(' ');
  }
  console.log(`  node ${n.name.padEnd(30)} t=(${t}) ${info}`);
}
const imgBytes = (i) => j.bufferViews[j.images[i].bufferView].byteLength;
const tex = (ti) => (ti === undefined ? null : j.textures[ti.index]);
const imgOf = (ti) => { const t = tex(ti); return t ? `${j.images[t.source].name}(${j.images[t.source].mimeType.split('/')[1]})` : '-'; };
console.log('materials:');
for (const m of j.materials) {
  const p = m.pbrMetallicRoughness || {};
  const occ = m.occlusionTexture ? `${imgOf(m.occlusionTexture)} uv${m.occlusionTexture.texCoord || 0}` : '-';
  console.log(`  ${m.name.padEnd(16)} base=${imgOf(p.baseColorTexture)} mr=${imgOf(p.metallicRoughnessTexture)} normal=${imgOf(m.normalTexture)}${m.normalTexture ? ' x' + (m.normalTexture.scale ?? 1) : ''} occ=${occ} alpha=${m.alphaMode || 'OPAQUE'} double=${!!m.doubleSided} factor=${JSON.stringify(p.baseColorFactor || '')}`);
  if (!m.normalTexture && !['Cobweb', 'Decal_Grime', 'Bakelite', 'Brass', 'Cord_Fabric', 'Glass_Bulb', 'Glass_Shard', 'Filament'].includes(m.name)) { ok = false; console.log('    ^ no normal map'); }
}
let tot = 0;
console.log('images:');
for (let i = 0; i < j.images.length; i++) { tot += imgBytes(i); console.log(`  ${j.images[i].name.padEnd(22)} ${j.images[i].mimeType} ${(imgBytes(i) / 1e6).toFixed(2)} MB`); }
console.log(`texture total ${(tot / 1e6).toFixed(2)} MB`);
if (size > 25e6) { ok = false; console.log('TOO LARGE'); }
process.exit(ok ? 0 : 1);
