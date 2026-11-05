/* What survives a "Refresh model", and the banner text for broken Revit rooms. Pure, so it is tested in node. */

/* The parts of the page state that loading a plan resets but a refresh should keep. */
function captureSession(state) {
  return {
    tourRooms: state.tourRooms.slice(),
    routeHandEdited: state.routeHandEdited,
    entrance: state.entrance,
    step: state.step,
    waypoints: state.waypoints,
  };
}

/* Puts them back; returns the step to go back to. */
function restoreSession(state, snap) {
  state.tourRooms = snap.tourRooms;
  state.routeHandEdited = snap.routeHandEdited;
  state.entrance = snap.entrance;
  state.waypoints = snap.waypoints;
  return snap.step;
}

const NOTICE_TEXT = {
  no_corridor: 'No corridor was found between the rooms, so Auto-path stays inside the building outline and tours are unavailable.',
  no_rooms: 'This level has no placed rooms. Auto-path works; tours need rooms.',
};

/* One line for the banner, or null when the level is fine. issues: [{problem}], notices: ['no_corridor', ...]. */
function bannerMessage(issues, notices) {
  const parts = [];
  if (issues && issues.length) {
    const counts = {};
    for (const i of issues) counts[i.problem] = (counts[i.problem] || 0) + 1;
    const detail = Object.entries(counts).map(([k, n]) => `${n} ${k.replace('_', ' ')}`).join(', ');
    parts.push(`${issues.length} Revit room${issues.length > 1 ? 's' : ''} look broken (${detail}). Auto-path still works, but tours may miss them.`);
  }
  for (const n of notices || []) if (NOTICE_TEXT[n]) parts.push(NOTICE_TEXT[n]);
  return parts.length ? parts.join(' ') : null;
}

if (typeof module === 'object') module.exports = { captureSession, restoreSession, bannerMessage };
