/* Maths for the 3D path view and the camera-view window. World space = the Revit model in metres, Z up, the same
   origin as the mesh vertices. Plan/canvas (display) space has y negated: world y = -display y * unitsToMetres.
   Yaw is display-space degrees, as in the engine: direction (cos yaw, sin yaw) in display space. */

const RAD = Math.PI / 180;
const FRAME_ASPECT = 16 / 9;

/* Route waypoints ([x, y, ...] in display units) as world points at eye height above the level's elevation. */
function routeToWorld(waypoints, unitsToMetres, eyeHeightM, elevationM = 0) {
  return waypoints.map(w => [w[0] * unitsToMetres, -w[1] * unitsToMetres, elevationM + eyeHeightM]);
}

/* Unit horizontal direction of a display-space yaw, in world space. */
function yawDirection(yawDeg) {
  return [Math.cos(yawDeg * RAD), -Math.sin(yawDeg * RAD)];
}

/* A camera cone: apex at the point, four base corners (16:9 frame) lengthM ahead, widened by the horizontal FOV. */
function coneParams(point, yawDeg, fovDeg, lengthM) {
  const [dx, dy] = yawDirection(yawDeg);
  const halfW = lengthM * Math.tan((fovDeg / 2) * RAD);
  const halfH = halfW / FRAME_ASPECT;
  const cx = point[0] + dx * lengthM, cy = point[1] + dy * lengthM;
  const sx = -dy * halfW, sy = dx * halfW;       // sideways, perpendicular to the view direction
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([s, v]) => [cx + sx * s, cy + sy * s, point[2] + halfH * v]);
  return { apex: [point[0], point[1], point[2]], baseCorners: corners };
}

function lerpYaw(a, b, f) {
  const d = ((b - a + 540) % 360) - 180;       // shortest way round
  return a + d * f;
}

/* Camera at fraction f (0..1) of the preview frames from /api/process-route: position, a point one metre ahead, FOV. */
function poseAt(frames, f, unitsToMetres, eyeHeightM) {
  const t = Math.min(1, Math.max(0, f));
  let i = 1;
  while (i < frames.length - 1 && frames[i].t < t) i++;
  const a = frames[Math.max(0, i - 1)], b = frames[Math.min(frames.length - 1, i)];
  const span = b.t - a.t;
  const k = span > 0 ? Math.min(1, Math.max(0, (t - a.t) / span)) : 0;
  const x = (a.x + (b.x - a.x) * k) * unitsToMetres;
  const y = -(a.y + (b.y - a.y) * k) * unitsToMetres;
  const yaw = lerpYaw(a.yaw, b.yaw, k);
  const [dx, dy] = yawDirection(yaw);
  return {
    position: [x, y, eyeHeightM],
    lookAt: [x + dx, y + dy, eyeHeightM],
    fovDeg: a.fov + (b.fov - a.fov) * k,
  };
}

/* [x, y] where a ray meets the horizontal plane z = floorZ, or null when it never does going forward. */
function floorHit(origin, dir, floorZ) {
  if (dir[2] >= 0) return null;
  const s = (floorZ - origin[2]) / dir[2];
  return s < 0 ? null : [origin[0] + dir[0] * s, origin[1] + dir[1] * s];
}

if (typeof module === 'object') module.exports = { routeToWorld, coneParams, poseAt, floorHit, yawDirection };
