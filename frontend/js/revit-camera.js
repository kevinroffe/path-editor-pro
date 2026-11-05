/* Pure parts of the "Revit camera" preview: which pose goes to Revit when, and what the message looks like. The host moves the
   active Revit 3D view's camera to each pose, so the pose rate is limited and a held pose is only ever the latest one. */

/* push(pose) returns the pose to send now, or null when it is held; take() returns the held (latest) pose once its time has come. */
function makeThrottle(intervalMs, nowFn) {
  let last = -Infinity, pending = null, sent = null;
  const same = (a, b) => !!a && !!b && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => a[k] === b[k]);
  return {
    /* A pose equal to the last one sent is never sent again: a paused video must not keep editing the Revit view. */
    push(pose) {
      const t = nowFn();
      if (same(pose, sent)) { pending = null; return null; }
      if (t - last >= intervalMs) { last = t; pending = null; sent = pose; return pose; }
      pending = pose;
      return null;
    },
    take() {
      if (pending === null) return null;
      const t = nowFn();
      if (t - last < intervalMs) return null;
      const pose = pending;
      pending = null;
      if (same(pose, sent)) return null;
      last = t; sent = pose;
      return pose;
    },
    /* A new preview starts: the next pose goes out even if it equals the last one of the previous run. */
    reset() { pending = null; sent = null; last = -Infinity; },
  };
}

/* The Revit camera only makes sense for a model that was read from Revit (a loaded JSON plan has no Revit coordinates). */
function cameraAllowed(source, insideRevit) {
  return source === 'revit' && !!insideRevit;
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

if (typeof module === 'object') module.exports = { makeThrottle, cameraMessage, frameAt, cameraAllowed };
