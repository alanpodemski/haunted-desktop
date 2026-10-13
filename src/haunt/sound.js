// All sound is synthesised with WebAudio (filtered noise and a few oscillators). Nothing is a sample.
// The listener is the camera; sources are panned in 3D. Footsteps behind the back wall go through a low-pass,
// the way sound through a plaster wall loses its highs.

export function createSound() {
  let ctx = null, master = null, noiseBuf = null, room = null, muted = false;

  function ensure() {
    if (ctx) return true;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = 0.9; master.connect(ctx.destination);
    // a short, dark room reverb from decaying noise
    const len = Math.floor(ctx.sampleRate * 1.6);
    const ir = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = ir.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.2);
    }
    room = ctx.createConvolver(); room.buffer = ir;
    const wet = ctx.createGain(); wet.gain.value = 0.32; room.connect(wet).connect(master);
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const nd = noiseBuf.getChannelData(0);
    for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;
    roomTone();
    scheduleCreak();
    return true;
  }

  const noise = (loop = false) => { const s = ctx.createBufferSource(); s.buffer = noiseBuf; s.loop = loop; return s; };
  const out = (node, wet = true) => { node.connect(master); if (wet) node.connect(room); };

  /** the room's own sound: low brown noise and a faint 50 Hz hum from wiring somewhere */
  function roomTone() {
    const n = noise(true);
    const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 180; lp.Q.value = 0.3;
    const g = ctx.createGain(); g.gain.value = 0.05;
    const lfo = ctx.createOscillator(); lfo.frequency.value = 0.07;
    const lg = ctx.createGain(); lg.gain.value = 0.02; lfo.connect(lg).connect(g.gain); lfo.start();
    n.connect(lp).connect(g); out(g, false); n.start();
    const hum = ctx.createOscillator(); hum.frequency.value = 50;
    const hg = ctx.createGain(); hg.gain.value = 0.004;
    hum.connect(hg); out(hg, false); hum.start();
  }

  /** old floorboards settle: a resonant stick-slip squeak with a falling pitch */
  function creak(gain = 0.05, pan = Math.random() * 2 - 1) {
    const t = ctx.currentTime;
    const n = noise();
    const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 18;
    const f0 = 380 + Math.random() * 400;
    bp.frequency.setValueAtTime(f0, t); bp.frequency.exponentialRampToValueAtTime(f0 * 0.6, t + 0.5);
    const am = ctx.createGain(); am.gain.value = 0;
    // stick-slip: a train of tiny bursts
    const dur = 0.35 + Math.random() * 0.5;
    for (let s = 0; s < dur; s += 0.012 + Math.random() * 0.02) {
      am.gain.setValueAtTime(gain * (0.5 + Math.random() * 0.5) * Math.sin(Math.PI * s / dur), t + s);
      am.gain.setValueAtTime(0, t + s + 0.006);
    }
    const p = ctx.createStereoPanner(); p.pan.value = pan;
    n.connect(bp).connect(am).connect(p); out(p);
    n.start(t); n.stop(t + dur + 0.1);
  }
  function scheduleCreak() {
    setTimeout(() => { if (!muted) creak(0.025 + Math.random() * 0.04); scheduleCreak(); }, 9000 + Math.random() * 22000);
  }

  function panner(pos) {
    const p = ctx.createPanner();
    p.panningModel = 'HRTF'; p.distanceModel = 'inverse'; p.refDistance = 1; p.rolloffFactor = 1.1;
    p.positionX.value = pos.x; p.positionY.value = pos.y; p.positionZ.value = pos.z;
    return p;
  }

  let listenerSet = false;
  return {
    /** call from a user gesture */
    unlock() { if (ensure() && ctx.state === 'suspended') ctx.resume(); return !!ctx; },
    get ready() { return !!ctx && ctx.state === 'running'; },
    setMuted(m) { muted = m; if (master) master.gain.value = m ? 0 : 0.9; },
    get muted() { return muted; },
    setListener(cam) {
      if (!ctx || listenerSet) return;
      const L = ctx.listener;
      const f = cam.getWorldDirection(cam.position.clone());
      if (L.positionX) {
        L.positionX.value = cam.position.x; L.positionY.value = cam.position.y; L.positionZ.value = cam.position.z;
        L.forwardX.value = f.x; L.forwardY.value = f.y; L.forwardZ.value = f.z;
        L.upX.value = 0; L.upY.value = 1; L.upZ.value = 0;
      }
      listenerSet = true;
    },
    /** a bare foot (or hand) on old boards: a low body thump plus a short scuff */
    footstep({ pos, kind = 'run', occluded = false, gain = 1 }) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const p = panner(pos);
      const lp = ctx.createBiquadFilter(); lp.type = 'lowpass';
      lp.frequency.value = occluded ? 420 : 2600;
      const g = ctx.createGain(); g.gain.value = 0;
      const amp = Math.min(1.2, gain) * (kind === 'crawl' ? 0.35 : 0.9) * (occluded ? 0.8 : 1);
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(amp, t + 0.004);
      g.gain.exponentialRampToValueAtTime(0.001, t + (kind === 'crawl' ? 0.06 : 0.14));
      const n = noise();
      const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = kind === 'crawl' ? 1400 : 260; bp.Q.value = 0.9;
      n.connect(bp).connect(g);
      const o = ctx.createOscillator(); o.type = 'sine';
      o.frequency.setValueAtTime(kind === 'crawl' ? 160 : 85, t); o.frequency.exponentialRampToValueAtTime(40, t + 0.1);
      const og = ctx.createGain(); og.gain.value = kind === 'crawl' ? 0.3 : 1.1;
      o.connect(og).connect(g);
      g.connect(lp).connect(p); out(p);
      n.start(t, Math.random()); n.stop(t + 0.2); o.start(t); o.stop(t + 0.16);
      if (Math.random() < 0.25) creak(0.05 * amp, 0);
    },
    /** caught it in the light: a low swell with a dissonant cluster, then a fast decay */
    sting(strength = 1) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const g = ctx.createGain(); g.gain.value = 0;
      g.gain.linearRampToValueAtTime(0.16 * strength, t + 0.03);
      g.gain.exponentialRampToValueAtTime(0.001, t + 2.4);
      for (const f of [55, 58.3, 82.4, 116.5, 233]) {
        const o = ctx.createOscillator(); o.type = f > 100 ? 'sawtooth' : 'triangle';
        o.frequency.setValueAtTime(f * 1.03, t); o.frequency.exponentialRampToValueAtTime(f * 0.97, t + 2.2);
        const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 900;
        o.connect(lp).connect(g); o.start(t); o.stop(t + 2.5);
      }
      const n = noise(); const hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 3000;
      const ng = ctx.createGain(); ng.gain.setValueAtTime(0.05 * strength, t); ng.gain.exponentialRampToValueAtTime(0.001, t + 0.6);
      n.connect(hp).connect(ng).connect(g); n.start(t); n.stop(t + 0.7);
      out(g);
    },
    /** the torch's slide switch */
    click(onState) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const n = noise(); const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = onState ? 3200 : 2600; bp.Q.value = 3;
      const g = ctx.createGain(); g.gain.setValueAtTime(0.25, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.03);
      n.connect(bp).connect(g); out(g, false); n.start(t); n.stop(t + 0.05);
    },
  };

  function ready() { return !!ctx && ctx.state === 'running'; }
}
