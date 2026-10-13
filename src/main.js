// main.js: the fake macOS desktop (DOM) over a live three.js wallpaper (the haunted room).
//
// Mouse: aims the flashlight. Drag a file onto the floor: it becomes a box (barricade the door). Drag boxes around,
// double-click one to put the file back.  Space: camera flash (a photo lands on the desktop).  F: flashlight.
// N: sound.  P: pause.  R: tidy the icons.  H: it comes for you now.  1–7: make it happen now (dash, crawl, walk, drag, watch, intrude,
// peek), for recording.
// URL: ?nohud hides the hint, ?hq renders at full Retina resolution, ?low below CSS resolution.

import { createDesktop } from './desktop/index.js';
import { createHaunt } from './haunt/scene.js';
import { createSound } from './haunt/sound.js';

const q = new URLSearchParams(location.search);

async function boot() {
  const sound = createSound();
  let dropHandler = null;
  const desk = await createDesktop(document.getElementById('desktop'), {
    liveWallpaper: true,
    // a file dropped onto the floor of the room becomes a box there
    onDrop: (icon, x, y) => (dropHandler ? dropHandler(icon, x, y) : false),
  });
  const haunt = await createHaunt(document.getElementById('scene'), { sound, desk, quality: q.has('hq') ? 2 : q.has('low') ? 0.5 : 1 });
  dropHandler = (icon, x, y) => haunt.boxes.drop(icon, x, y);

  addEventListener('pointermove', (e) => haunt.setPointer(e.clientX, e.clientY), { passive: true });
  const hint = document.getElementById('hint');
  if (q.has('nohud')) hint.remove();
  else setTimeout(() => hint.classList.add('gone'), 7000);

  const unlock = () => { sound.unlock(); };
  addEventListener('pointerdown', unlock);
  addEventListener('keydown', unlock);

  const EVENTS = ['dash', 'crawl', 'walk', 'drag', 'watch', 'intrude', 'peek'];
  addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'f') sound.click(haunt.flashlight.toggle());
    else if (k === 'n') sound.setMuted(!sound.muted);
    else if (k === ' ') { haunt.photo.shoot(); e.preventDefault(); }
    else if (k === 'p') haunt.pause();
    else if (k === 'h') haunt.creature.trigger('hunt');
    else if (k === 'r') desk.relayout();       // tidy the icons it scattered
    else if (/^[1-7]$/.test(k)) haunt.creature.trigger(EVENTS[Number(k) - 1]);
  });

  window.__haunt = { desk, haunt, sound };
}

boot().catch((err) => {
  console.error('[haunt] boot failed', err);
  const el = document.createElement('pre');
  el.style.cssText = 'position:fixed;left:12px;top:48px;color:#fff;background:rgba(200,0,0,.8);padding:8px 12px;border-radius:8px;z-index:9999;font:12px monospace';
  el.textContent = 'boot failed: ' + (err && err.stack || err);
  document.body.appendChild(el);
});
