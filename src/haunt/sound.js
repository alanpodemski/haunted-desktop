// Sound: recorded effects (public/sfx/*.mp3, made with scripts/gen-sounds.mjs) where they exist, and the
// synthesised WebAudio versions (filtered noise and oscillators) as the fallback. The listener is the camera;
// sources are panned in 3D. Sounds from behind a wall go through a low-pass, the way a plaster wall eats the highs.

export function createSound() {
  let ctx = null, master = null, noiseBuf = null, room = null, muted = false;
  let scrapeNode = null, droneNode = null;

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
    loadSamples();
    return true;
  }

  // ---- recorded effects
  const buffers = new Map();
  const levels = new Map();      // name -> { gain, lead }: loudness matching and the silence to skip at the start
  let ambience = null;
  /** measure a recording: RMS of its loud part, its peak, and where the sound actually starts */
  function analyse(name, buf) {
    const d = buf.getChannelData(0);
    let peak = 0;
    for (let i = 0; i < d.length; i++) { const a = Math.abs(d[i]); if (a > peak) peak = a; }
    const step = /^(step|crawl|box_thud)/.test(name);
    const th = peak * (step ? 0.12 : 0.04);
    let start = 0; while (start < d.length && Math.abs(d[start]) < th) start++;
    let sum = 0, n = 0;
    for (let i = start; i < d.length; i++) { if (Math.abs(d[i]) > peak * 0.02) { sum += d[i] * d[i]; n++; } }
    const rms = Math.sqrt(sum / Math.max(1, n));
    // footsteps and knocks are matched by peak, everything else by loudness
    const want = step ? 0.6 / Math.max(1e-4, peak) : (name === 'ambience' || name === 'rain' ? 0.05 : 0.11) / Math.max(1e-4, rms);
    levels.set(name, { gain: Math.min(8, want), lead: Math.max(0, start / buf.sampleRate - 0.005), peak, rms });
  }
  async function loadSamples() {
    let list = [];
    try { list = await (await fetch('/sfx/index.json', { cache: 'no-cache' })).json(); } catch { return; }
    await Promise.all(list.map(async ({ name }) => {
      try {
        const b = await ctx.decodeAudioData(await (await fetch(`/sfx/${name}.mp3`, { cache: 'no-cache' })).arrayBuffer());
        analyse(name, b);
        // a generation that came out (nearly) silent is left out rather than amplified into hiss
        // (only impacts are expected to be loud; distant sounds are quiet on purpose and get matched up)
        const pk = levels.get(name).peak;
        if (pk >= (/^(step|crawl|box_thud)/.test(name) ? 0.08 : 0.005)) buffers.set(name, b);
      } catch { /* skip */ }
    }));
    beds();
  }
  // the beds that never stop: the house's room tone and the storm outside. Started as soon as the audio is running
  // (it may still be resuming when the recordings finish loading), retried until they play.
  let rain = null;
  function beds() {
    if (!ambience && buffers.has('ambience')) ambience = play('ambience', { loop: true, gain: 0.45, wet: false });
    if (!rain && buffers.has('rain')) rain = play('rain', { loop: true, gain: 0.75, wet: false });
    if ((!ambience && buffers.has('ambience')) || (!rain && buffers.has('rain'))) setTimeout(beds, 500);
  }
  const variants = (prefix) => [...buffers.keys()].filter((k) => k === prefix || k.startsWith(prefix + '_'));
  const has = (prefix) => variants(prefix).length > 0;
  /** play a recording (a random variant of `prefix`); returns { stop, setPos, setGain } or null */
  function play(prefix, { pos = null, gain = 1, rate = 1, occluded = false, loop = false, wet = true, fadeIn = 0 } = {}) {
    if (!ready() || muted) return null;
    const vs = variants(prefix);
    if (!vs.length) return null;
    const src = ctx.createBufferSource();
    const pickName = vs[Math.floor(Math.random() * vs.length)];
    src.buffer = buffers.get(pickName);
    const lv = levels.get(pickName) || { gain: 1, lead: 0 };
    gain *= lv.gain;
    src.loop = loop; src.playbackRate.value = rate;
    const g = ctx.createGain();
    const t = ctx.currentTime;
    if (fadeIn > 0) { g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(gain, t + fadeIn); } else g.gain.value = gain;
    let node = src.connect(g);
    if (occluded) { const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 600; node = node.connect(lp); }
    let p = null;
    if (pos) { p = panner(pos); node = node.connect(p); }
    out(node, wet);
    src.start(t, loop ? 0 : lv.lead);
    return {
      stop(fade = 0.3) { const e = ctx.currentTime; g.gain.cancelScheduledValues(e); g.gain.setTargetAtTime(0, e, fade / 3); src.stop(e + fade + 0.1); },
      setPos(v) { if (p) { p.positionX.value = v.x; p.positionY.value = v.y; p.positionZ.value = v.z; } },
      setGain(v) { g.gain.setTargetAtTime(v, ctx.currentTime, 0.1); },
    };
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
  const api = {
    /** call from a user gesture */
    unlock() { if (ensure() && ctx.state === 'suspended') ctx.resume(); return !!ctx; },
    get ready() { return !!ctx && ctx.state === 'running'; },
    setMuted(m) { muted = m; if (!m) beds(); if (master) master.gain.value = m ? 0 : 0.9; },
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
    /** a cardboard box landing or being hit: a hollow, low thump whose pitch drops with the box's size */
    thud({ pos, strength = 0.5, size = 0.5 }) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const p = panner(pos);
      const g = ctx.createGain();
      const a = Math.min(1, strength) * 0.7;
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(a, t + 0.003);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.18 + size * 0.15);
      const n = noise();
      const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 520 - size * 300; bp.Q.value = 1.4;
      n.connect(bp).connect(g);
      const o = ctx.createOscillator(); o.frequency.setValueAtTime(140 - size * 70, t); o.frequency.exponentialRampToValueAtTime(45, t + 0.15);
      const og = ctx.createGain(); og.gain.value = 0.8; o.connect(og).connect(g);
      g.connect(p); out(p);
      n.start(t, Math.random()); n.stop(t + 0.4); o.start(t); o.stop(t + 0.3);
    },
    /** a box dragged over floorboards: filtered noise while the hand holds it */
    scrape(on) {
      if (!ready()) return;
      if (on && !scrapeNode) {
        const n = noise(true);
        const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 900; bp.Q.value = 0.7;
        const g = ctx.createGain(); g.gain.value = 0;
        g.gain.setTargetAtTime(muted ? 0 : 0.03, ctx.currentTime, 0.05);
        n.connect(bp).connect(g); out(g); n.start();
        scrapeNode = { n, g };
      } else if (!on && scrapeNode) {
        const { n, g } = scrapeNode; scrapeNode = null;
        g.gain.setTargetAtTime(0, ctx.currentTime, 0.05); n.stop(ctx.currentTime + 0.3);
      }
    },
    /** the camera: shutter, the flash tube's pop, then the capacitor recharging (a rising whine) */
    shutter(rechargeSeconds = 4) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      for (const [dt, f] of [[0, 4200], [0.045, 2600]]) {
        const n = noise(); const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = f; bp.Q.value = 2;
        const g = ctx.createGain(); g.gain.setValueAtTime(0.35, t + dt); g.gain.exponentialRampToValueAtTime(0.001, t + dt + 0.035);
        n.connect(bp).connect(g); out(g); n.start(t + dt); n.stop(t + dt + 0.06);
      }
      const o = ctx.createOscillator(); o.type = 'sine';
      o.frequency.setValueAtTime(1800, t + 0.15); o.frequency.exponentialRampToValueAtTime(9000, t + rechargeSeconds);
      const g = ctx.createGain(); g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.012, t + 0.4);
      g.gain.setValueAtTime(0.012, t + rechargeSeconds - 0.1); g.gain.linearRampToValueAtTime(0, t + rechargeSeconds);
      o.connect(g); out(g, false); o.start(t + 0.15); o.stop(t + rechargeSeconds + 0.05);
    },
    /** a low, beating drone while it is hunting you */
    drone(on) {
      if (!ready()) return;
      if (on && !droneNode) {
        const g = ctx.createGain(); g.gain.value = 0; g.gain.setTargetAtTime(muted ? 0 : 0.06, ctx.currentTime, 1.5);
        const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 400;
        const oscs = [41, 41.7, 61.5, 82.6].map((f) => { const o = ctx.createOscillator(); o.type = 'sawtooth'; o.frequency.value = f; o.connect(lp); o.start(); return o; });
        lp.connect(g); out(g);
        droneNode = { g, oscs };
      } else if (!on && droneNode) {
        const { g, oscs } = droneNode; droneNode = null;
        g.gain.setTargetAtTime(0, ctx.currentTime, 0.8);
        for (const o of oscs) o.stop(ctx.currentTime + 4);
      }
    },
    /** it is in your face: a shriek (formant-filtered noise and a detuned saw cluster) */
    shriek() {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const g = ctx.createGain(); g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.5, t + 0.02);
      g.gain.setValueAtTime(0.5, t + 0.6); g.gain.exponentialRampToValueAtTime(0.001, t + 1.6);
      const n = noise();
      for (const [f, q] of [[800, 6], [1150, 8], [2900, 10]]) {
        const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = q;
        bp.frequency.setValueAtTime(f * 0.8, t); bp.frequency.linearRampToValueAtTime(f * 1.2, t + 0.5);
        n.connect(bp).connect(g);
      }
      for (const f of [310, 329, 466]) {
        const o = ctx.createOscillator(); o.type = 'sawtooth';
        o.frequency.setValueAtTime(f, t); o.frequency.linearRampToValueAtTime(f * 1.3, t + 0.5);
        const og = ctx.createGain(); og.gain.value = 0.12; o.connect(og).connect(g); o.start(t); o.stop(t + 1.7);
      }
      out(g); n.start(t); n.stop(t + 1.7);
    },
    /** cardboard tearing: a ripping burst of filtered noise */
    tear(pos) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const n = noise();
      const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.setValueAtTime(1800, t); bp.frequency.linearRampToValueAtTime(900, t + 0.35); bp.Q.value = 1.2;
      const g = ctx.createGain(); g.gain.value = 0;
      for (let s2 = 0; s2 < 0.35; s2 += 0.008 + Math.random() * 0.012) { g.gain.setValueAtTime(0.25 + Math.random() * 0.25, t + s2); g.gain.setValueAtTime(0.02, t + s2 + 0.004); }
      g.gain.setValueAtTime(0, t + 0.4);
      const p = panner(pos);
      n.connect(bp).connect(g).connect(p); out(p); n.start(t, Math.random()); n.stop(t + 0.45);
    },
    /** a door swinging on old hinges */
    doorCreak(pos, amount = 0.5) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const n = noise();
      const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 22;
      const f0 = 520 + Math.random() * 380;
      bp.frequency.setValueAtTime(f0, t); bp.frequency.linearRampToValueAtTime(f0 * (0.7 + Math.random() * 0.6), t + 0.5);
      const am = ctx.createGain(); am.gain.value = 0;
      for (let s2 = 0; s2 < 0.5; s2 += 0.01 + Math.random() * 0.025) {
        am.gain.setValueAtTime(0.14 * amount * (0.5 + Math.random() * 0.5), t + s2);
        am.gain.setValueAtTime(0, t + s2 + 0.006);
      }
      const p = panner(pos);
      n.connect(bp).connect(am).connect(p); out(p); n.start(t); n.stop(t + 0.6);
    },
    /** thunder: a crack, then a long low roll (lowpassed noise with slow swells) */
    thunder(strength = 1) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const n = noise(true);
      const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.setValueAtTime(900, t); lp.frequency.exponentialRampToValueAtTime(90, t + 1.2);
      const g = ctx.createGain(); g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.5 * strength, t + 0.05);
      let tt = t + 0.3;
      for (let i = 0; i < 5; i++) { g.gain.linearRampToValueAtTime((0.15 + Math.random() * 0.3) * strength, tt); tt += 0.4 + Math.random() * 0.6; }
      g.gain.exponentialRampToValueAtTime(0.001, tt + 2.5);
      n.connect(lp).connect(g); out(g); n.start(t); n.stop(tt + 2.7);
    },
    /** a match struck and the wick catching */
    match() {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const n = noise(); const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 2400; bp.Q.value = 0.8;
      const g = ctx.createGain(); g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.18, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.02, t + 0.25); g.gain.exponentialRampToValueAtTime(0.001, t + 0.9);
      n.connect(bp).connect(g); out(g); n.start(t); n.stop(t + 1);
    },
    /** the flame went out: a soft breath */
    puff(pos) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const n = noise(); const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 700;
      const g = ctx.createGain(); g.gain.setValueAtTime(0.12, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
      const p = panner(pos); n.connect(lp).connect(g).connect(p); out(p); n.start(t); n.stop(t + 0.4);
    },
    /** a road flare: a hard ignition crack, then a sputtering hiss while it burns; returns { stop } */
    flareHiss() {
      if (!ready()) return null;
      const t = ctx.currentTime;
      const n = noise(true);
      const hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 1800;
      const g = ctx.createGain(); g.gain.setValueAtTime(muted ? 0 : 0.25, t); g.gain.exponentialRampToValueAtTime(muted ? 0.0001 : 0.05, t + 0.6);
      const lfo = ctx.createOscillator(); lfo.frequency.value = 13; const lg = ctx.createGain(); lg.gain.value = 0.02;
      lfo.connect(lg).connect(g.gain); lfo.start();
      n.connect(hp).connect(g); out(g); n.start(t);
      return { stop() { const e = ctx.currentTime; g.gain.cancelScheduledValues(e); g.gain.setTargetAtTime(0, e, 0.3); n.stop(e + 1.5); lfo.stop(e + 1.5); } };
    },
    /** a music box: a slow, minor waltz on a comb of tuned steel teeth (sines with a fast bell decay); returns { stop, setPos } */
    musicBox() {
      if (!ready()) return null;
      const p = panner({ x: 0, y: 0, z: -3 });
      const g = ctx.createGain(); g.gain.value = muted ? 0 : 0.5; g.connect(p); out(p);
      // "Für Elise"-like turn, transposed down and left unresolved
      const tune = [76, 75, 76, 75, 76, 71, 74, 72, 69, 0, 60, 64, 69, 71, 0, 64, 68, 71, 72, 0, 64, 76, 75, 76, 75, 76, 71, 74, 72, 69];
      let i = 0, stopped = false, rate = 0.36;
      const tick = () => {
        if (stopped) return;
        const n = tune[i % tune.length]; i++;
        if (n) {
          const t = ctx.currentTime;
          const f = 440 * Math.pow(2, (n - 69) / 12);
          for (const [mult, amp] of [[1, 0.6], [3.98, 0.12], [8.1, 0.04]]) {
            const o = ctx.createOscillator(); o.frequency.value = f * mult * (1 + (Math.random() - 0.5) * 0.004);
            const e = ctx.createGain(); e.gain.setValueAtTime(amp, t); e.gain.exponentialRampToValueAtTime(0.0005, t + 1.6 / mult);
            o.connect(e).connect(g); o.start(t); o.stop(t + 1.7);
          }
        }
        rate *= 1.004;        // the spring runs down
        setTimeout(tick, rate * 1000);
      };
      tick();
      return {
        stop() { stopped = true; g.gain.setTargetAtTime(0, ctx.currentTime, 0.2); },
        setPos(v) { p.positionX.value = v.x; p.positionY.value = v.y; p.positionZ.value = v.z; },
      };
    },
    /** wood and a steel comb breaking */
    smash(pos) {
      if (!ready() || muted) return;
      const t = ctx.currentTime;
      const p = panner(pos);
      const g = ctx.createGain(); g.gain.setValueAtTime(0.6, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.7);
      const n = noise(); const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = 1100; bp.Q.value = 0.9;
      n.connect(bp).connect(g);
      for (const f of [1318, 1661, 2093, 2794]) {
        const o = ctx.createOscillator(); o.frequency.value = f;
        const e = ctx.createGain(); e.gain.setValueAtTime(0.06, t + 0.02); e.gain.exponentialRampToValueAtTime(0.0005, t + 1.2);
        o.connect(e).connect(g); o.start(t + 0.02); o.stop(t + 1.3);
      }
      g.connect(p); out(p); n.start(t); n.stop(t + 0.8);
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

  // ---- prefer the recordings where there are some
  const synth = { ...api };
  let lastCreak = 0;
  Object.assign(api, {
    has,
    /** a recorded voice or sound, positioned (see play) */
    voice(prefix, opts) { return play(prefix, opts); },
    footstep(o) {
      if (!has('step_walk') && !has('step_run')) return synth.footstep(o);
      const name = o.kind === 'crawl' && has('crawl') ? 'crawl' : o.gain < 0.55 ? 'step_walk' : 'step_run';
      play(name, { pos: o.pos, gain: Math.min(1.2, 0.35 + o.gain * 0.7), rate: 0.9 + Math.random() * 0.2, occluded: o.occluded });
    },
    shriek() { if (!play('shriek', { gain: 1.1, wet: false })) synth.shriek(); },
    sting(strength = 1) { synth.sting(strength * 0.6); play('growl', { gain: 0.9 * strength, wet: false }); },
    thunder(strength = 1) { if (!play('thunder', { gain: 0.9 * strength })) synth.thunder(strength); },
    doorCreak(pos, amount = 0.5) {
      const now = ctx ? ctx.currentTime : 0;
      if (has('door_creak')) { if (now - lastCreak > 1.6) { lastCreak = now; play('door_creak', { pos, gain: 0.5 + amount * 0.6, rate: 0.85 + Math.random() * 0.3 }); } }
      else synth.doorCreak(pos, amount);
    },
    tear(pos) { if (!play('box_tear', { pos, gain: 1 })) synth.tear(pos); },
    thud(o) { if (o.strength > 0.7 && has('box_thud')) play('box_thud', { pos: o.pos, gain: Math.min(1, o.strength * 0.7), rate: 1.1 - o.size * 0.3 }); else synth.thud(o); },
    shutter(sec) { if (!play('camera_flash', { gain: 0.8, wet: false })) synth.shutter(sec); },
    flareHiss() { play('flare_ignite', { gain: 0.8 }); return synth.flareHiss(); },
    musicBox() {
      const h = play('music_box', { pos: { x: 0, y: 0, z: -3 }, loop: true, gain: 0.8 });
      return h ? { stop: () => h.stop(0.6), setPos: (v) => h.setPos(v) } : synth.musicBox();
    },
  });
  // (a getter: Object.assign would have copied its value once)
  Object.defineProperty(api, 'levels', { get: () => Object.fromEntries([...levels].map(([k, v]) => [k, { gain: +v.gain.toFixed(2), lead: +v.lead.toFixed(3), peak: +v.peak.toFixed(2), rms: +v.rms.toFixed(3) }])) });
  return api;

  function ready() { return !!ctx && ctx.state === 'running'; }
}
