/* Four commercial-real-estate music themes generated with the Web Audio API — no audio files.
   A theme is a one-loop pattern of notes; the player schedules it ahead of time and loops it. */

const midiToHz = m => 440 * 2 ** ((m - 69) / 12);

/* Chord tones (MIDI) per bar, in a middle register; roots for the bass are an octave or two below. */
const PROGRESSIONS = {
  'premium-lobby': [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 64]],
  'modern-workspace': [[57, 60, 64], [53, 57, 60], [60, 64, 67], [55, 59, 62]],
  'bright-leasing': [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]],
  'cinematic-reveal': [[50, 53, 57], [46, 50, 53], [53, 57, 60], [48, 52, 55]],
};

const BPMS = { 'premium-lobby': 70, 'modern-workspace': 100, 'bright-leasing': 118, 'cinematic-reveal': 64 };

const note = (beat, midi, beats, vel, voice) => ({ beat, midi, beats, vel, voice });

/* One bar of each theme, starting at beat b with chord c. */
const BAR = {
  'premium-lobby': (b, c) => [
    ...c.map(m => note(b, m, 4, 0.18, 'pad')),
    note(b, c[0] - 24, 4, 0.4, 'bass'),
    ...[[0, 2], [1.5, 1], [2, 3], [3, 2]].map(([at, i]) => note(b + at, c[i % c.length] + 12, 1, 0.45, 'keys')),
  ],
  'modern-workspace': (b, c) => [
    ...c.map(m => note(b, m, 4, 0.12, 'pad')),
    ...[0, 1.5, 2, 3.5].map(at => note(b + at, c[0] - 24, 0.5, 0.5, 'bass')),
    ...Array.from({ length: 8 }, (_, k) => note(b + k / 2, c[k % c.length] + 12, 0.25, 0.22, 'pulse')),
  ],
  'bright-leasing': (b, c) => [
    ...[0, 1, 2, 3].map(at => note(b + at, c[0] - 24, 0.75, 0.5, 'bass')),
    ...[0, 1.5, 2.5, 3].flatMap(at => c.map(m => note(b + at, m + 12, 0.5, 0.2, 'keys'))),
    ...Array.from({ length: 8 }, (_, k) => note(b + k / 2, c[(k + 1) % c.length] + 24, 0.25, 0.14, 'pulse')),
  ],
  'cinematic-reveal': (b, c, bar) => [
    ...c.map(m => note(b, m, 4, 0.26, 'pad')),
    note(b, c[0] - 24, 4, 0.45, 'bass'),
    note(b, 69 + [0, 2, 3, 5][bar], 4, 0.35, 'keys'),
  ],
};

/* One seamless loop of a theme: four bars of four beats. */
function themePattern(id) {
  const chords = PROGRESSIONS[id] || PROGRESSIONS['premium-lobby'];
  const key = PROGRESSIONS[id] ? id : 'premium-lobby';
  return { bpm: BPMS[key], bars: chords.length, notes: chords.flatMap((c, bar) => BAR[key](bar * 4, c, bar)) };
}

/* How full the theme sounds at second t of total: Cinematic reveal swells, the others stay level. */
function intensityAt(id, t, total) {
  return id === 'cinematic-reveal' ? 0.35 + 0.65 * Math.min(1, total > 0 ? t / total : 0) : 1;
}

const VOICES = {
  pad: { type: 'triangle', attack: 0.6, release: 0.8, peak: 1 },
  keys: { type: 'triangle', attack: 0.005, release: 1.2, peak: 1, pluck: true },
  pulse: { type: 'square', attack: 0.005, release: 0.12, peak: 0.6, pluck: true },
  bass: { type: 'sine', attack: 0.01, release: 0.15, peak: 1 },
};

const LOOKAHEAD_S = 0.6;
const TICK_MS = 100;
const SAMPLE_S = 6;

/* Plays one theme in time with the preview: start(at, total) from timeline second `at`, stop() to pause. */
function createMusicPlayer(makeContext = () => new AudioContext()) {
  let ctx = null, master = null, filter = null, timer = null, live = [];
  let theme = 'premium-lobby', volume = 0.7;
  let run = null; // { atS, totalS, ctxStart, nextBeat, envelope }

  const ensure = () => {
    if (ctx) return;
    ctx = makeContext();
    master = ctx.createGain();
    master.gain.value = 0;
    filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 2600;
    filter.connect(master).connect(ctx.destination);
  };

  const playNote = (n, when, beatS) => {
    const v = VOICES[n.voice], osc = ctx.createOscillator(), env = ctx.createGain();
    const len = n.beats * beatS, end = when + len + v.release;
    osc.type = v.type;
    osc.frequency.value = midiToHz(n.midi);
    env.gain.setValueAtTime(0, when);
    env.gain.linearRampToValueAtTime(n.vel * v.peak, when + v.attack);
    if (v.pluck) env.gain.exponentialRampToValueAtTime(0.0001, end);
    else {
      env.gain.setValueAtTime(n.vel * v.peak, when + Math.max(v.attack, len));
      env.gain.linearRampToValueAtTime(0, end);
    }
    osc.connect(env).connect(filter);
    osc.start(when);
    osc.stop(end + 0.05);
    live.push(osc);
    osc.onended = () => { live = live.filter(o => o !== osc); };
  };

  const tick = () => {
    if (!run) return;
    const p = themePattern(theme), beatS = 60 / p.bpm, loopBeats = p.bars * 4;
    const now = ctx.currentTime, t = run.atS + (now - run.ctxStart);
    master.gain.setTargetAtTime(volume * run.envelope(t) * intensityAt(theme, t, run.totalS), now, 0.08);
    const horizonBeat = (t + LOOKAHEAD_S) / beatS;
    while (run.nextBeat < horizonBeat) {
      const loop = Math.floor(run.nextBeat / loopBeats), within = run.nextBeat - loop * loopBeats;
      const nextNote = p.notes.map(n => n.beat).filter(b => b >= within - 1e-9).sort((a, b) => a - b)[0];
      const beat = nextNote === undefined ? (loop + 1) * loopBeats : loop * loopBeats + nextNote;
      if (beat >= horizonBeat) { run.nextBeat = beat; break; }
      const when = run.ctxStart + (beat * beatS - run.atS);
      p.notes.filter(n => Math.abs(n.beat - (beat - loop * loopBeats)) < 1e-9)
        .forEach(n => playNote(n, Math.max(now, when), beatS));
      run.nextBeat = beat + 1e-6;
    }
  };

  const begin = (atS, totalS, envelope) => {
    ensure();
    halt();
    if (ctx.state === 'suspended') ctx.resume();
    const beatS = 60 / themePattern(theme).bpm;
    run = { atS, totalS, ctxStart: ctx.currentTime + 0.05, nextBeat: atS / beatS, envelope };
    tick();
    timer = setInterval(tick, TICK_MS);
  };

  const halt = () => {
    clearInterval(timer);
    timer = null;
    run = null;
    if (!ctx) return;
    master.gain.cancelScheduledValues(ctx.currentTime);
    master.gain.setTargetAtTime(0, ctx.currentTime, 0.05);
    live.forEach(o => { try { o.stop(ctx.currentTime + 0.2); } catch { /* already stopped */ } });
    live = [];
  };

  return {
    setTheme(id) {
      theme = PROGRESSIONS[id] ? id : 'premium-lobby';
      if (run) begin(run.atS + (ctx.currentTime - run.ctxStart), run.totalS, run.envelope);
    },
    setVolume(v) { volume = Math.min(1, Math.max(0, v)); },
    /* Create and resume the audio context inside a user gesture, so later playback is allowed. */
    prime() {
      ensure();
      if (ctx.state === 'suspended') ctx.resume();
    },
    start(atS, totalS) {
      const gainAt = typeof musicGain === 'function' ? musicGain : () => 1;
      begin(atS, totalS, t => gainAt(t, totalS));
    },
    stop: halt,
    sample(id) {
      theme = PROGRESSIONS[id] ? id : theme;
      begin(0, SAMPLE_S, t => Math.max(0, Math.min(1, t / 0.3, (SAMPLE_S - t) / 0.6)));
      const mine = run;
      setTimeout(() => { if (run === mine) halt(); }, SAMPLE_S * 1000);
    },
    get playing() { return !!run; },
  };
}

if (typeof module === 'object') module.exports = { midiToHz, themePattern, intensityAt, createMusicPlayer };
