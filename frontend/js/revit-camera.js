/* Pure parts of the "Revit camera" preview: which pose goes to Revit when, and what the message looks like. The host moves the
   active Revit 3D view's camera to each pose, so the pose rate is limited and a held pose is only ever the latest one. */

/* push(pose) returns the pose to send now, or null when it is held; take() returns the held (latest) pose once its time has come. */
function makeThrottle(intervalMs, nowFn) {
  let last = -Infinity, pending = null;
  return {
    push(pose) {
      const t = nowFn();
      if (t - last >= intervalMs) { last = t; pending = null; return pose; }
      pending = pose;
      return null;
    },
    take() {
      if (pending === null) return null;
      const t = nowFn();
      if (t - last < intervalMs) return null;
      const pose = pending;
      pending = null; last = t;
      return pose;
    },
  };
}

/* The message the add-in understands: plan position (feet), yaw (plan degrees) and the level's height in feet. */
function cameraMessage(frame, elevationFt) {
  return { type: 'camera', x: frame.x, y: frame.y, yaw: frame.yaw, elevation: Number.isFinite(elevationFt) ? elevationFt : 0 };
}

/* The preview frame at fraction t (0..1) of the walk: position blended, yaw the short way round; null without frames. */
function frameAt(frames, t) {
  if (!frames || !frames.length) return null;
  if (frames.length === 1) return frames[0];
  const n = frames.length, raw = Math.min(1, Math.max(0, t)) * (n - 1);
  const i = Math.min(Math.floor(raw), n - 2), k = raw - i, a = frames[i], b = frames[i + 1];
  const turn = ((b.yaw - a.yaw + 540) % 360) - 180;
  return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, yaw: a.yaw + turn * k };
}

if (typeof module === 'object') module.exports = { makeThrottle, cameraMessage, frameAt };
