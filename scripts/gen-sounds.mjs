// Generates the game's recorded sounds with the ElevenLabs Sound Effects API into public/sfx/.
//
//   node scripts/gen-sounds.mjs            # makes the ones that are missing
//   node scripts/gen-sounds.mjs --force    # makes all of them again
//   node scripts/gen-sounds.mjs moan_1     # just these
//
// The key is read from ELEVENLABS_API_KEY (environment, or .env.local, which git ignores). It is never printed.

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'public', 'sfx');

function apiKey() {
  if (process.env.ELEVENLABS_API_KEY) return process.env.ELEVENLABS_API_KEY.trim();
  try {
    const env = readFileSync(join(ROOT, '.env.local'), 'utf8');
    const m = env.match(/^ELEVENLABS_API_KEY\s*=\s*"?([^"\n]+)"?/m);
    if (m) return m[1].trim();
  } catch { /* no file */ }
  return null;
}

// name, seconds (0.5–22), prompt influence (0–1: how literally to follow the text), prompt
export const SOUNDS = [
  // the creature
  ['breath_close_1', 4, 0.6, 'heavy, wet, raspy breathing of an emaciated monster very close to the microphone, slow ragged inhale and exhale, horror game, no music'],
  ['breath_close_2', 4, 0.6, 'a starving undead creature panting through its mouth close by, rattling throat, horror, dry room, no music'],
  ['breath_far', 5, 0.5, 'distant ragged breathing echoing down an empty wooden hallway at night, faint, horror, no music'],
  ['growl_1', 2.5, 0.6, 'low guttural zombie growl, wet throat, close, horror game creature, no music'],
  ['growl_2', 2, 0.6, 'short aggressive snarl of a feral undead man, throaty, horror, no music'],
  ['moan_1', 4, 0.5, 'long mournful zombie moan echoing from a room down a hallway, reverberant, horror, no music'],
  ['moan_2', 3.5, 0.5, 'a low groaning wail of a dead man from behind a wall, muffled, horror, no music'],
  ['shriek_1', 2, 0.7, 'sudden inhuman shriek of a monster lunging at the camera, jump scare scream, horror game, no music'],
  ['shriek_2', 1.6, 0.7, 'piercing distorted screech of a zombie in your face, jump scare, horror, no music'],
  ['scream_far', 3, 0.5, 'a monster screaming in a hallway, then running away, reverberant, horror, no music'],
  // the house
  ['laugh_child', 2.5, 0.5, 'a faint creepy child giggle far away in an empty house, reverb, horror, no music'],
  ['laugh_whisper', 2, 0.6, 'a breathy whispered laugh very close to the ear, unsettling, horror ASMR, no music'],
  ['whisper', 4, 0.5, 'unintelligible creepy whispering close to the listener, several voices, horror, no music'],
  ['door_creak_1', 2.5, 0.6, 'an old wooden door slowly creaking open on rusty hinges, quiet room, no music'],
  ['door_creak_2', 1.5, 0.6, 'a short squeak of an old door hinge, close, no music'],
  ['thunder_1', 7, 0.5, 'a loud crack of thunder nearby followed by a long rolling rumble, heard from inside an old house, rain on windows, no music'],
  ['thunder_2', 6, 0.5, 'distant thunder rumble rolling across the sky, heard indoors, no music'],
  ['rain', 22, 0.5, 'steady heavy rain on old windows and a roof heard from inside a dark wooden house, gusts of wind, no thunder, seamless loop, no music'],
  ['ambience', 22, 0.4, 'dark ambient room tone of an abandoned house at night, wind outside, very faint creaks, low drone, seamless loop, no music'],
  // footsteps of a heavy barefoot man on old floorboards
  ['step_walk_1', 0.6, 0.7, 'a single slow heavy bare footstep on an old creaky wooden floorboard, close, dry, no music'],
  ['step_walk_2', 0.6, 0.7, 'one dragging bare footstep on old wooden floor, scuff, close, no music'],
  ['step_walk_3', 0.6, 0.7, 'a single heavy barefoot step on a wooden floor with a small creak, no music'],
  ['step_run_1', 0.8, 0.8, 'one loud heavy thud of a bare foot slamming onto an old wooden floor while running, single impact, close, no music'],
  ['step_run_3', 0.8, 0.8, 'one loud barefoot slap on a wooden hallway floor, a heavy running step, close, no music'],
  ['crawl_1', 0.6, 0.7, 'hands and knees slapping a wooden floor once, something crawling fast, no music'],
  // your things
  ['box_tear', 1, 0.7, 'a cardboard box being torn apart violently, ripping and crushing, no music'],
  ['box_thud', 0.6, 0.7, 'a heavy cardboard box dropped on a wooden floor, hollow thump, no music'],
  ['flare_ignite', 3, 0.6, 'a road flare being struck and igniting, fizzing hiss of burning magnesium, no music'],
  ['camera_flash', 1.5, 0.7, 'an old camera shutter click and a flash firing, then the capacitor recharge whine, no music'],
  ['music_box', 12, 0.6, 'an old music box slowly playing a sad, slightly out of tune waltz, winding down, no other music'],
];

async function generate(key, [name, seconds, influence, text]) {
  const res = await fetch('https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128', {
    method: 'POST',
    headers: { 'xi-api-key': key, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
    body: JSON.stringify({ text, duration_seconds: seconds, prompt_influence: influence }),
  });
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status} ${(await res.text()).slice(0, 300)}`);
  const buf = Buffer.from(await res.arrayBuffer());
  writeFileSync(join(OUT, `${name}.mp3`), buf);
  return buf.length;
}

async function main() {
  const key = apiKey();
  if (!key) { console.error('No ELEVENLABS_API_KEY in the environment or .env.local'); process.exit(1); }
  mkdirSync(OUT, { recursive: true });
  const args = process.argv.slice(2);
  const force = args.includes('--force');
  const only = args.filter((a) => !a.startsWith('--'));
  const todo = SOUNDS.filter(([n]) => (only.length ? only.includes(n) : force || !existsSync(join(OUT, `${n}.mp3`))));
  console.log(`generating ${todo.length} sound(s)`);
  for (const s of todo) {
    try { console.log(`  ${s[0]}  ${(await generate(key, s) / 1024).toFixed(0)} KB`); }
    catch (err) { console.error(`  ${err.message}`); }
  }
  writeFileSync(join(OUT, 'index.json'), JSON.stringify(SOUNDS.map(([n, sec]) => ({ name: n, seconds: sec })).filter(({ name }) => existsSync(join(OUT, `${name}.mp3`))), null, 2));
}

main();
