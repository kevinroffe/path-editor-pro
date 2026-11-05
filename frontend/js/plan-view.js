/* What the path means, drawn on the 2D plan: where the camera looks at each point (a cone), where it stands still (a ring), and
   the preview frame nearest a point. Plan space = the page's display space: x as in Revit, y negated; a yaw of 0 looks along +x
   and 90 along +y (the engine's convention). Pure, so it is tested in node. */

const DEFAULT_FOV = 60;

/* Apex first, then the two far corners of the cone, len away at yaw minus and plus half the field of view. */
function viewCone(x, y, yawDeg, fovDeg, len) {
  const fov = Number.isFinite(fovDeg) && fovDeg > 5 && fovDeg < 170 ? fovDeg : DEFAULT_FOV;   // a silly value gives a sane cone
  const half = (fov / 2) * Math.PI / 180, yaw = yawDeg * Math.PI / 180;
  const corner = s => [x + len * Math.cos(yaw + s), y + len * Math.sin(yaw + s)];
  return [[x, y], corner(-half), corner(half)];
}

/* A cone long enough to read on this plan: a twentieth of its longer side (a fallback when there is no plan yet). */
function coneLength(bounds) {
  if (!bounds) return 2;
  return Math.max(Math.max(bounds.xmax - bounds.xmin, bounds.ymax - bounds.ymin) / 20, 0.5);
}

/* The planned keyframes where the camera stands still (a pan, a hold or a cut gap). */
function pauseKeyframes(plan) {
  return plan && Array.isArray(plan.keyframes) ? plan.keyframes.filter(k => k.still_s > 0) : [];
}

/* The preview frame closest to (x, y), or null when there are no frames. */
function nearestFrame(frames, x, y) {
  if (!frames || !frames.length) return null;
  let best = frames[0], bestD = Infinity;
  for (const f of frames) {
    const d = (f.x - x) ** 2 + (f.y - y) ** 2;
    if (d < bestD) { bestD = d; best = f; }
  }
  return best;
}

if (typeof module === 'object') module.exports = { viewCone, coneLength, pauseKeyframes, nearestFrame };
