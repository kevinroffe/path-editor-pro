/* Preview-only video timeline: intro card → walk (with fades that skip part of it) → outro card.
   Times are seconds; distances are metres along the route; frames are evenly spaced in walk time. */

const INTRO_S = 3;
const OUTRO_S = 3;
const FADE_S = 0.8;
const HALF_FADE_S = FADE_S / 2;
const MIN_FADE_M = 0.5;
const MUSIC_OUT_S = 2;

/* Cumulative metres per frame, first 0. */
function routeDistances(frames, unitsToMetres) {
  const out = frames.length ? [0] : [];
  for (let i = 1; i < frames.length; i++) {
    const a = frames[i - 1], b = frames[i];
    out.push(out[i - 1] + Math.hypot(b.x - a.x, b.y - a.y) * unitsToMetres);
  }
  return out;
}

/* Walk seconds of the first moment the route reaches d metres. */
function walkTimeAtDistance(dists, walkSeconds, d) {
  const n = dists.length;
  if (n < 2 || d <= 0) return 0;
  const i = dists.findIndex(x => x >= d);
  if (i < 0) return walkSeconds;
  const a = dists[i - 1], b = dists[i];
  const frac = b > a ? (d - a) / (b - a) : 0;
  return Math.min(walkSeconds, Math.max(0, ((i - 1 + frac) / (n - 1)) * walkSeconds));
}

/* A new fade from aM to bM, or the reason it is refused. */
function makeFade(aM, bM, fades, lengthM) {
  const outM = Math.min(lengthM, Math.max(0, aM));
  const inM = Math.min(lengthM, Math.max(0, bM));
  if (inM < outM) return { error: 'Pick the fade-in point further along the path than the fade-out point.' };
  if (inM - outM < MIN_FADE_M) return { error: 'Pick two points at least half a metre apart.' };
  if (fades.some(f => outM < f.inM && inM > f.outM)) return { error: "Fades can't overlap. Pick points outside the existing fade." };
  return { fade: { outM, inM } };
}

/* Fades that still fit on a route of lengthM metres. */
function pruneFades(fades, lengthM) {
  return fades.filter(f => f.outM < f.inM && f.inM <= lengthM);
}

/* Blocks laid end to end; fades out of order or overlapping an earlier one are skipped. */
function buildTimeline({ dists, walkSeconds, fades }) {
  const blocks = [{ kind: 'intro', start: 0, end: INTRO_S, walkFrom: null, walkTo: null }];
  const push = (kind, len, walkFrom, walkTo) => {
    const start = blocks[blocks.length - 1].end;
    blocks.push({ kind, start, end: start + len, walkFrom, walkTo });
  };
  let w = 0;
  for (const f of [...fades].sort((p, q) => p.outM - q.outM)) {
    const a = walkTimeAtDistance(dists, walkSeconds, f.outM);
    const b = walkTimeAtDistance(dists, walkSeconds, f.inM);
    if (a < w || b <= a) continue;
    if (a > w) push('walk', a - w, w, a);
    push('fade', FADE_S, a, b);
    w = b;
  }
  if (walkSeconds > w) push('walk', walkSeconds - w, w, walkSeconds);
  push('outro', OUTRO_S, null, null);
  return { total: blocks[blocks.length - 1].end, walkSeconds, blocks };
}

/* What the preview shows at timeline second t. */
function sampleTimeline(tl, t) {
  const tc = Math.min(tl.total, Math.max(0, t));
  const block = tl.blocks.findLast(b => b.start <= tc) || tl.blocks[0];
  const local = tc - block.start;
  if (block.kind === 'intro') return { kind: 'intro', walkS: 0, black: 0, card: 'intro' };
  if (block.kind === 'outro') return { kind: 'outro', walkS: tl.walkSeconds, black: 0, card: 'outro' };
  if (block.kind === 'walk') return { kind: 'walk', walkS: block.walkFrom + local, black: 0, card: null };
  const black = Math.round(Math.max(0, 1 - Math.abs(local - HALF_FADE_S) / HALF_FADE_S) * 1e6) / 1e6;
  return { kind: 'fade', walkS: local < HALF_FADE_S ? block.walkFrom : block.walkTo, black, card: null };
}

/* Music level: rises over the intro card, falls over the last two seconds. */
function musicGain(t, total) {
  const fadeIn = Math.min(1, t / INTRO_S);
  const fadeOut = Math.min(1, (total - t) / MUSIC_OUT_S);
  return Math.max(0, Math.min(fadeIn, fadeOut));
}

/* Metres along the route of the nearest route point to plan point (x, y). */
function projectToRoute(frames, dists, unitsToMetres, x, y) {
  let best = { d2: Infinity, m: 0 };
  for (let i = 1; i < frames.length; i++) {
    const a = frames[i - 1], b = frames[i];
    const dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
    const s = len2 ? Math.min(1, Math.max(0, ((x - a.x) * dx + (y - a.y) * dy) / len2)) : 0;
    const px = a.x + s * dx, py = a.y + s * dy, d2 = (x - px) ** 2 + (y - py) ** 2;
    if (d2 < best.d2) best = { d2, m: dists[i - 1] + s * Math.sqrt(len2) * unitsToMetres };
  }
  return best.m;
}

if (typeof module === 'object') {
  module.exports = {
    INTRO_S, OUTRO_S, FADE_S, routeDistances, walkTimeAtDistance, makeFade, pruneFades,
    buildTimeline, sampleTimeline, musicGain, projectToRoute,
  };
}
