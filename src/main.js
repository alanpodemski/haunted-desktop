// main.js: the fake macOS desktop (DOM) over a live three.js wallpaper (the haunted room).
//
// Mouse: aims the flashlight. Drag a file onto the floor: it becomes a box (barricade the door). Drag boxes around,
// double-click one to put the file back. Select many (rubber band, Cmd-A, Shift-click) and drop them together.  Space: camera flash (a photo lands on the desktop).  F: flashlight.
// N: sound.  P: pause.  R: tidy the icons.  L: lightning.  H: it comes for you now.  1–7: make it happen now (cross, wander, dash,
// crawl, peek, endwatch, hunt), for recording.
// ?: show or hide the controls legend.
// URL: ?nohud hides the legend, ?hq renders at full Retina resolution, ?low below CSS resolution.

import { createDesktop } from './desktop/index.js';
import { createHaunt } from './haunt/scene.js';
import { createSound } from './haunt/sound.js';
import { itemType, renderItemIcons } from './haunt/items.js';

const q = new URLSearchParams(location.search);

async function boot() {
  const sound = createSound();
  let dropHandler = null;
  const desk = await createDesktop(document.getElementById('desktop'), {
    liveWallpaper: true,
    // a file dropped onto the floor of the room becomes a box there
    onDrop: (icon, x, y) => (dropHandler ? dropHandler(icon, x, y) : false),
    // a whole selection dropped into the room: folders and documents stack into a wall, tools get used
    onDropMany: (icons, x, y) => (dropManyHandler ? dropManyHandler(icons, x, y) : []),
  });
  let dropManyHandler = null;
  const haunt = await createHaunt(document.getElementById('scene'), { sound, desk, quality: q.has('hq') ? 2 : q.has('low') ? 0.5 : 1 });
  // folders and documents become boxes; .usdz files are the things you defend yourself with
  dropHandler = (icon, x, y) => {
    if (!itemType(icon.name)) return haunt.boxes.drop(icon, x, y);
    const ok = haunt.items.drop(icon, x, y);
    if (ok) haunt.boxes.markBuild();
    return ok;
  };
  dropManyHandler = (icons, x, y) => {
    // a selection builds a wall from its folders and documents; tools are used one at a time, so they stay
    // behind (unless the selection is only tools)
    const tools = icons.filter((i) => itemType(i.name)), stuff = icons.filter((i) => !itemType(i.name));
    if (stuff.length) return haunt.boxes.dropMany(stuff, x, y);
    const taken = [];
    tools.forEach((ic, i) => {
      const a = i * 2.4, r = 18 + 10 * i;      // spread a little so candles do not land inside each other
      if (haunt.items.drop(ic, x + Math.cos(a) * r, y + Math.sin(a) * r * 0.5)) taken.push(ic.id);
    });
    haunt.boxes.markBuild();
    return taken;
  };
  // their icons: 3D thumbnails of the same models, as Finder shows .usdz files
  const thumbs = renderItemIcons();
  for (const ic of desk.getIcons()) { const t = itemType(ic.name); if (t) desk.renameIcon(ic.id, ic.name, thumbs[t]); }

  addEventListener('pointermove', (e) => haunt.setPointer(e.clientX, e.clientY), { passive: true });
  // the controls legend: stays until you hide it (? key or ✕); remembered per browser
  const legend = document.getElementById('legend');
  const store = { get() { try { return localStorage.getItem('legend'); } catch { return null; } }, set(v) { try { localStorage.setItem('legend', v); } catch { /* private mode */ } } };
  const setLegend = (min) => { legend.classList.toggle('min', min); legend.querySelector('.x').textContent = min ? '?' : '✕'; store.set(min ? 'min' : 'open'); };
  if (q.has('nohud')) legend.remove();
  else {
    setLegend(store.get() === 'min');
    legend.querySelector('.x').addEventListener('click', () => setLegend(!legend.classList.contains('min')));
    legend.addEventListener('pointerdown', (e) => e.stopPropagation());
  }

  const unlock = () => { sound.unlock(); };
  addEventListener('pointerdown', unlock);
  addEventListener('keydown', unlock);

  const EVENTS = ['cross', 'wander', 'dash', 'crawl', 'peek', 'endwatch', 'hunt'];
  addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'f') sound.click(haunt.flashlight.toggle());
    else if (k === 'n') sound.setMuted(!sound.muted);
    else if (k === ' ') { haunt.photo.shoot(); e.preventDefault(); }
    else if (k === 'p') haunt.pause();
    else if (k === 'h') haunt.creature.trigger('hunt');
    else if (k === 'r') desk.relayout();       // tidy the icons it scattered
    else if (k === 'l') haunt.strike();         // lightning
    else if (k === '?' || k === '/') { if (legend.isConnected) setLegend(!legend.classList.contains('min')); }
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
