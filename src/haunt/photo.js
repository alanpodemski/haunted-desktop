// The camera. Space fires a flash: a very bright, very short light at the lens that shows the whole room for an
// instant. The frame is saved as a photo on the desktop (IMG_0667.jpeg …) with a date stamp. Sometimes the photo
// shows it standing somewhere you did not see it: it is posed for the photo's render only, never the live view.
// A flash in its face during a hunt drives it back. The flash needs ~4 s to recharge.

import * as THREE from 'three';

const RECHARGE = 4;

export function createPhoto({ renderer, scene, camera, post, creature, desk, sound }) {
  const flash = new THREE.PointLight(0xf4f1ff, 0, 0, 2);
  flash.position.copy(camera.position).add(new THREE.Vector3(0.05, 0.06, -0.05));
  scene.add(flash);
  const FLASH_CANDELA = 150;          // a small xenon tube: a few hundred cd·s over ~1/1000 s, held for a frame here

  let readyAt = 0, number = 667, shots = 0, ghosted = 0;
  let pending = null;                  // a flash requested for the next frame
  let decay = 0;

  function stamp(g, w, h) {
    // the orange seven-segment-looking date stamp of a cheap camera
    const d = new Date();
    const mon = d.toLocaleString('en-US', { month: 'short' }).toUpperCase();
    const txt = `${mon} ${String(d.getDate()).padStart(2, ' ')} '${String(d.getFullYear()).slice(2)}  ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
    g.font = `600 ${Math.round(h * 0.042)}px "Courier New", ui-monospace, monospace`;
    g.textAlign = 'right';
    g.shadowColor = 'rgba(255,90,0,0.8)'; g.shadowBlur = h * 0.01;
    g.fillStyle = 'rgba(255,150,40,0.92)';
    g.fillText(txt, w * 0.95, h * 0.93);
    g.shadowBlur = 0;
  }

  function capture() {
    const src = renderer.domElement;
    const w = 1200, h = Math.round(w * src.height / src.width);
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.drawImage(src, 0, 0, w, h);
    // a flash photo's look: hot centre, falloff to the corners, a little extra grain
    const v = g.createRadialGradient(w / 2, h / 2, h * 0.2, w / 2, h / 2, w * 0.7);
    v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(0,0,0,0.55)');
    g.fillStyle = v; g.fillRect(0, 0, w, h);
    stamp(g, w, h);
    const url = c.toDataURL('image/jpeg', 0.86);
    // Finder-style thumbnail: the picture fitted into a square icon
    const t = document.createElement('canvas'); t.width = t.height = 256;
    const tg = t.getContext('2d');
    const tw = 240, th = Math.round(tw * h / w);
    tg.shadowColor = 'rgba(0,0,0,0.45)'; tg.shadowBlur = 6; tg.shadowOffsetY = 2;
    tg.fillStyle = '#fff'; tg.fillRect(8 - 3, (256 - th) / 2 - 3, tw + 6, th + 6);
    tg.shadowBlur = 0; tg.shadowOffsetY = 0;
    tg.drawImage(c, 8, (256 - th) / 2, tw, th);
    return { url, thumb: t.toDataURL('image/png') };
  }

  // ---- Quick Look style viewer
  const photos = new Map();
  let ql = null;
  function open(id) {
    const p = photos.get(id);
    if (!p) return;
    close();
    ql = document.createElement('div');
    ql.className = 'ql-window';
    ql.innerHTML = `<div class="ql-bar"><span class="ql-close"></span><span class="ql-title"></span></div><img class="ql-img" alt="">`;
    ql.querySelector('.ql-title').textContent = p.name;
    ql.querySelector('.ql-img').src = p.url;
    ql.querySelector('.ql-close').addEventListener('click', close);
    document.body.appendChild(ql);
  }
  function close() { if (ql) { ql.remove(); ql = null; } }
  addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  desk.onIconOpen((icon) => open(icon.id));

  return {
    get ready() { return performance.now() / 1000 >= readyAt; },
    get viewerOpen() { return !!ql; },
    close,
    /** Space: fire the flash on the next frame (if charged) */
    shoot() {
      const now = performance.now() / 1000;
      if (now < readyAt) return false;
      readyAt = now + RECHARGE;
      pending = true;
      sound && sound.shutter(RECHARGE);
      return true;
    },
    /** instead of post.render(): renders the photo frame when a flash is due, then the live frame */
    render(time) {
      if (!pending) {
        if (decay > 0) { decay = Math.max(0, decay - 1); flash.intensity = FLASH_CANDELA * (decay / 3) * 0.15; }
        else flash.intensity = 0;
        post.render(time);
        return;
      }
      pending = false;
      shots++;
      // sometimes it is in the picture: never in the first one, and for sure by the third if not before
      const want = shots >= 2 && !creature.hunting && (ghosted === 0 && shots >= 3 ? true : Math.random() < 0.3);
      const unstage = want ? creature.stageForPhoto() : null;
      if (unstage) ghosted++;
      flash.intensity = FLASH_CANDELA;
      post.render(time);
      const shot = capture();
      if (unstage) {
        unstage();
        post.render(time);           // the frame you actually see: the same flash, without it
      }
      decay = 3;
      creature.onFlash();
      const name = `IMG_${String(number++).padStart(4, '0')}.jpeg`;
      const id = desk.addIcon({ id: `photo-${number}`, name, kind: 'jpeg', ext: 'jpeg', bytes: 2_600_000 + Math.random() * 900_000, icon: shot.thumb });
      photos.set(id, { name, url: shot.url });
    },
  };
}
