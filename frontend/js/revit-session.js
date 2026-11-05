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

/* What a level change asks the add-in for. While the frame is up, or before any model was loaded, the user has not framed
   that level yet, so it asks for the overview (the frame shows on the new level). After a load it re-reads the 2D in the same
   area and keeps the 3D the engine already has. */
function levelChangeRequest(cropping, loadedOnce, level, lastBox) {
  if (cropping || !loadedOnce) return { type: 'overview', level };
  return { type: 'readModel', level, crop: lastBox, keep_meshes: true };
}

/* Switching to the Top view the first time: re-read the same area with the 3D (2D alone is the default). */
function meshRequest(level, lastBox) {
  return { type: 'readModel', level, crop: lastBox, meshes: true };
}

/* A read asks for the 3D when the preview pane is open or the plan is in Top view; otherwise 2D alone is the faster default. */
function wantsMeshes(mode, previewOn) {
  return mode === 'top' || !!previewOn;
}

/* The header chip: which Revit 3D view the model comes from (the user hides categories there to shape the 3D). */
function syncLabel(viewName) {
  return viewName ? `3D view: ${viewName}` : 'Synced with Revit ✓';
}

if (typeof module === 'object') module.exports = { captureSession, restoreSession, bannerMessage, levelChangeRequest, meshRequest, wantsMeshes, syncLabel };
