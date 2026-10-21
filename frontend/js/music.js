/* Four bundled music tracks (see frontend/audio/CREDITS.md), played in time with the preview.
   A track that is shorter than the video loops, each pass crossfading into the next. */

const TRACKS = {
  'premium-lobby': { file: 'frontend/audio/premium-lobby.mp3', title: 'Your Breath', artist: 'Eugenio Mininni', durationS: 236 },
  'modern-workspace': { file: 'frontend/audio/modern-workspace.mp3', title: 'Focus on Yourself', artist: 'Eugenio Mininni', durationS: 286 },
  'bright-leasing': { file: 'frontend/audio/bright-leasing.mp3', title: 'Motivating Mornings', artist: 'Ahjay Stelino', durationS: 96 },
  'cinematic-reveal': { file: 'frontend/audio/cinematic-reveal.mp3', title: 'Drawing the Sky', artist: 'Eugenio Mininni', durationS: 207 },
};

const LOOP_CROSSFADE_S = 2;
const SAMPLE_S = 15;
const SAMPLE_IN_S = 0.3;
const SAMPLE_OUT_S = 1;
const ENVELOPE_STEP_S = 0.1;
const START_DELAY_S = 0.05;

/* Position in the newest pass of a looping track at timeline second atS. */
function trackOffset(atS, durS) {
  return atS % (durS - LOOP_CROSSFADE_S);
}

/* The passes of the track sounding between timeline seconds atS and totalS: when each starts,
   where in the track it begins, and whether it crossfades with the pass before / after it. */
function loopPasses(atS, totalS, durS) {
  const period = durS - LOOP_CROSSFADE_S, passes = [];
  for (let at = 0; at < totalS; at += period) {
    if (at + durS > atS) passes.push({ at, offset: Math.max(0, atS - at), fadeIn: at > 0, fadeOut: at + period < totalS });
  }
  return passes;
}

const decoded = new Map();

/* The decoded track for a theme, fetched and decoded once per page. */
function loadTrack(id, ctx) {
  if (!decoded.has(id)) {
    const p = fetch(TRACKS[id].file)
      .then(r => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${TRACKS[id].file}: HTTP ${r.status}`))))
      .then(bytes => (ctx || new OfflineAudioContext(2, 1, 48000)).decodeAudioData(bytes));
    p.catch(() => decoded.delete(id));
    decoded.set(id, p);
  }
  return decoded.get(id);
}

const envelopeOf = totalS => {
  const gainAt = typeof musicGain === 'function' ? musicGain : () => 1;
  return t => gainAt(t, totalS);
};

/* Ramp a gain param through sorted (timeline second, value) points, from timeline second atS onwards. */
function rampThrough(param, points, atS, ctxStart) {
  const when = t => ctxStart + t - atS;
  const after = points.filter(([t]) => t > atS), before = points.filter(([t]) => t <= atS).at(-1);
  const next = after[0];
  const start = before && next
    ? before[1] + (next[1] - before[1]) * (atS - before[0]) / (next[0] - before[0])
    : (before || next)[1];
  param.setValueAtTime(start, when(atS));
  after.forEach(([t, v]) => param.linearRampToValueAtTime(v, when(t)));
}

/* Schedule a track from timeline second atS to totalS into dest, timeline second atS sounding at
   context time ctxStart; returns the envelope gain and the sources so a caller can stop them. */
function scheduleMix(ctx, dest, buffer, atS, totalS, ctxStart, envelope) {
  const env = ctx.createGain(), dur = buffer.duration;
  env.connect(dest);
  const steps = Math.max(1, Math.ceil((totalS - atS) / ENVELOPE_STEP_S));
  rampThrough(env.gain, Array.from({ length: steps + 1 }, (_, i) => {
    const t = Math.min(totalS, atS + i * ENVELOPE_STEP_S);
    return [t, envelope(t)];
  }), atS, ctxStart);
  const sources = loopPasses(atS, totalS, dur).map(p => {
    const src = ctx.createBufferSource(), fade = ctx.createGain(), end = p.at + dur;
    src.buffer = buffer;
    src.connect(fade).connect(env);
    rampThrough(fade.gain, [
      [p.at, p.fadeIn ? 0 : 1], [p.at + LOOP_CROSSFADE_S, 1],
      [end - LOOP_CROSSFADE_S, 1], [end, p.fadeOut ? 0 : 1],
    ], atS, ctxStart);
    src.start(ctxStart + Math.max(0, p.at - atS), p.offset);
    src.stop(ctxStart + Math.min(end, totalS) - atS + START_DELAY_S);
    return src;
  });
  return { env, sources };
}

/* Plays one theme in time with the preview: start(at, total) from timeline second `at`, stop() to pause. */
function createMusicPlayer(makeContext = () => new AudioContext()) {
  let ctx = null, out = null, run = null, theme = 'premium-lobby', volume = 0.7;

  const ensure = () => {
    if (ctx) return;
    ctx = makeContext();
    out = ctx.createGain();
    out.gain.value = volume;
    out.connect(ctx.destination);
  };

  const halt = () => {
    const was = run;
    run = null;
    if (!was?.mix) return;
    const now = ctx.currentTime;
    was.mix.env.gain.cancelScheduledValues(now);
    was.mix.env.gain.setTargetAtTime(0, now, 0.03);
    was.mix.sources.forEach(s => { try { s.stop(now + 0.2); } catch { /* already stopped */ } });
  };

  /* Play from timeline second atS once the track is decoded; with catchUp, skip the time spent loading
     so the music stays in step with a preview that kept moving. */
  const begin = (atS, totalS, envelope, catchUp) => {
    ensure();
    halt();
    if (ctx.state === 'suspended') ctx.resume();
    const mine = run = { atS, totalS, envelope, id: theme, askedAt: ctx.currentTime, mix: null };
    return loadTrack(theme, ctx).then(buffer => {
      if (run !== mine) return;
      mine.ctxStart = ctx.currentTime + START_DELAY_S;
      if (catchUp) mine.atS += mine.ctxStart - mine.askedAt;
      if (mine.atS < totalS) mine.mix = scheduleMix(ctx, out, buffer, mine.atS, totalS, mine.ctxStart, envelope);
    }, err => {
      if (run === mine) run = null;
      throw err;
    });
  };

  const position = () => run.atS + ctx.currentTime - (run.ctxStart ?? run.askedAt);
  const warn = err => console.warn('Music unavailable:', err);

  return {
    setTheme(id) {
      theme = TRACKS[id] ? id : 'premium-lobby';
      if (run && run.id !== theme) begin(position(), run.totalS, run.envelope, true).catch(warn);
      else if (!run && ctx) loadTrack(theme, ctx).catch(warn);
    },
    setVolume(v) {
      volume = Math.min(1, Math.max(0, v));
      if (out) out.gain.setTargetAtTime(volume, ctx.currentTime, 0.05);
    },
    /* Create and resume the audio context inside a user gesture, so later playback is allowed. */
    prime() {
      ensure();
      if (ctx.state === 'suspended') ctx.resume();
    },
    start(atS, totalS) {
      begin(atS, totalS, envelopeOf(totalS), true).catch(warn);
    },
    stop: halt,
    /* Play the first 15 s of a theme's track; resolves once it is playing, rejects if it cannot load. */
    sample(id) {
      theme = TRACKS[id] ? id : theme;
      const playing = begin(0, SAMPLE_S, t => Math.max(0, Math.min(1, t / SAMPLE_IN_S, (SAMPLE_S - t) / SAMPLE_OUT_S)), false);
      const mine = run;
      playing.then(() => setTimeout(() => { if (run === mine) halt(); }, (SAMPLE_S + 0.3) * 1000), () => {});
      return playing;
    },
    get playing() { return !!run; },
  };
}

/* The music for a whole video as one buffer: same envelope, volume and looping as the preview. */
async function renderMusicMix(id, totalS, volume, sampleRate = 48000) {
  const ctx = new OfflineAudioContext(2, Math.max(1, Math.ceil(totalS * sampleRate)), sampleRate);
  const buffer = await loadTrack(TRACKS[id] ? id : 'premium-lobby', ctx);
  const out = ctx.createGain();
  out.gain.value = Math.min(1, Math.max(0, volume));
  out.connect(ctx.destination);
  scheduleMix(ctx, out, buffer, 0, totalS, 0, envelopeOf(totalS));
  return ctx.startRendering();
}

if (typeof module === 'object') {
  module.exports = { TRACKS, LOOP_CROSSFADE_S, trackOffset, loopPasses, loadTrack, createMusicPlayer, renderMusicMix };
}
