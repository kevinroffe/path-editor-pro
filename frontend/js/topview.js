/* The "Top view" mode of the plan canvas: the 3D model seen from straight above, drawn once into a picture that sits under the
   plan's overlays (route, points, cones, the you-are-here dot), so zoom, pan and editing work exactly as on the plan.
   These are the pure parts (where the picture goes, how the camera frames it, where it cuts); revit-shell.js renders it. */

const CUT_M = 2.6;                          // metres above the level: walls and furniture show, ceilings and roofs above are cut away

/* Where the picture goes in plan (display) space: x as in Revit, y negated, so the top edge is at -ymax. */
function underlayPlacement(bounds) {
  if (!bounds) return null;
  return { x: bounds.xmin, y: -bounds.ymax, width: bounds.xmax - bounds.xmin, height: bounds.ymax - bounds.ymin };
}

/* An orthographic camera over the middle of the plan: its frame size in metres and the point it hangs over (three space,
   z = minus model y). */
function topCamera(bounds, unitsToMetres) {
  if (!bounds) return null;
  const u = unitsToMetres;
  return {
    width: (bounds.xmax - bounds.xmin) * u, height: (bounds.ymax - bounds.ymin) * u,
    cx: (bounds.xmin + bounds.xmax) / 2 * u, cz: -(bounds.ymin + bounds.ymax) / 2 * u,
  };
}

/* Pixel size of the picture: the plan's proportions with the longer side at maxPx (every side at least 1). */
function imageSize(bounds, maxPx) {
  if (!bounds) return null;
  const w = bounds.xmax - bounds.xmin, h = bounds.ymax - bounds.ymin, k = maxPx / Math.max(w, h);
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) };
}

/* Height in metres above which the model is cut away. */
function clipHeight(levelElevationM, cutM) {
  return levelElevationM + cutM;
}

/* Mesh types that are never drawn in the top view (they would hide everything below). */
function hiddenTypes() {
  return new Set(['roof', 'ceiling', 'light']);
}

if (typeof module === 'object') module.exports = { CUT_M, underlayPlacement, topCamera, imageSize, clipHeight, hiddenTypes };
