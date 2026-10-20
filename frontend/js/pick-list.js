/* The rooms picked for the tour, and how per-room choices survive a rebuild of the route. */

const MAX_PANS = 2;

const QUICK_ADD = {
  offices: /office/i,
  meeting: /conference|meeting|board/i,
  amenities: /kitchen|comfort|lounge|break|cafe|pantry/i,
};

/* next with each stop's dwell and Stand & look copied from prev's stop in the same room; pans capped in route order. */
function carryStopSettings(prev, next) {
  const kept = new Map(prev.filter(w => w.stop?.room_id).map(w => [w.stop.room_id, w.stop]));
  let pans = 0;
  return next.map(w => {
    if (!w.stop) return { ...w };
    const old = kept.get(w.stop.room_id);
    const stop = old ? { ...w.stop, dwell_s: old.dwell_s, pan: !!old.pan } : { ...w.stop };
    if (stop.pan && ++pans > MAX_PANS) stop.pan = false;
    return { ...w, stop };
  });
}

/* Stop room ids in route order, each once. */
function pickListFromWaypoints(waypoints) {
  return [...new Set(waypoints.map(w => w.stop?.room_id).filter(Boolean))];
}

/* picked plus the rooms of one quick-add group, in plan order. */
function quickAdd(rooms, picked, group) {
  const have = new Set(picked);
  return [...picked, ...rooms.filter(r => QUICK_ADD[group].test(r.type || '') && !have.has(r.id)).map(r => r.id)];
}

/* Whether stop i may switch Stand & look to `on`. */
function canSetPan(waypoints, i, on) {
  return !on || waypoints.filter((w, j) => j !== i && w.stop?.pan).length < MAX_PANS;
}

if (typeof module === 'object') {
  module.exports = { MAX_PANS, QUICK_ADD, carryStopSettings, pickListFromWaypoints, quickAdd, canSetPan };
}
