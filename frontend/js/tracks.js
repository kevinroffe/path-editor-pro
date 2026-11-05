/* Lanes for the Revit window's timeline: video, camera keyframes, look-at, pauses, music.
   All times are timeline seconds (intro card included), so they line up with the play head. */

const TL = (typeof require === 'function') ? require('./video-timeline.js') : { routeDistances, buildTimeline, INTRO_S, OUTRO_S };

/* Timeline second of walk second w: inside a walk block it is linear; a moment skipped by a fade lands on the fade. */
function timelineSecondAt(tl, w) {
  for (const b of tl.blocks) {
    if (b.kind === 'walk' && w >= b.walkFrom && w <= b.walkTo) return b.start + (w - b.walkFrom);
    if (b.kind === 'fade' && w >= b.walkFrom && w <= b.walkTo) return b.start;
  }
  const last = tl.blocks.filter(b => b.kind !== 'outro').pop();       // out of range: the end of the walk
  return last ? last.end : 0;
}

/* plan: the /api/camera-plan JSON. frames (optional): the evenly spaced preview frames, for exact fade distances.
   fades: [{outM, inM}]. music: { id } or null. plain: just the walk (no intro, outro, fades or music), times from zero. */
function buildTracks({ plan, frames, fades, music, plain }) {
  const kfs = plan.keyframes;
  const u = plan.units_to_metres;
  const walkSeconds = kfs.length ? kfs[kfs.length - 1].t_s : 0;
  const dists = TL.routeDistances(frames && frames.length ? frames : kfs, u);
  const tl = plain
    ? { total: walkSeconds, walkSeconds, blocks: [{ kind: 'walk', start: 0, end: walkSeconds, walkFrom: 0, walkTo: walkSeconds }] }
    : TL.buildTimeline({ dists, walkSeconds, fades: fades || [] });
  const at = i => timelineSecondAt(tl, kfs[i].t_s);

  const video = tl.blocks.map((b, i) => ({ id: `blk:${i}`, startS: b.start, endS: b.end, kind: b.kind }));
  const camera = kfs.map((k, i) => ({ id: `kf:${i}`, startS: at(i), endS: at(i), kind: 'keyframe' }));
  const lookat = kfs.slice(1).map((_, i) => ({ id: `look:${i}`, startS: at(i), endS: at(i + 1), kind: 'look', yaw: kfs[i].yaw }));
  const pauses = kfs.flatMap((k, i) => (k.still_s > 0 ? [{ id: `pause:${i}`, startS: at(i), endS: at(i) + k.still_s, kind: 'pause' }] : []));
  const musicClips = !plain && music && music.id ? [{ id: 'music', startS: 0, endS: tl.total, kind: music.id }] : [];

  return {
    durationS: tl.total,
    lanes: [
      { id: 'video', clips: video }, { id: 'camera', clips: camera }, { id: 'lookat', clips: lookat },
      { id: 'pauses', clips: pauses }, { id: 'music', clips: musicClips },
    ],
  };
}

if (typeof module === 'object') module.exports = { buildTracks, timelineSecondAt };
