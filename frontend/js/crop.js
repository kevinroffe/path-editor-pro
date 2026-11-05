/* The frame the user drags around the plan before the model is read. Rectangles live in plan (display) space, where y is the
   negated Revit y, as {x0, y0, x1, y1} with x0 < x1 and y0 < y1. The add-in wants model space ({xmin, ymin, xmax, ymax}). */

function normaliseRect(a, b) {
  return { x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y), x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y) };
}

const clip = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/* The part of the frame that lies inside bounds; a frame wholly outside collapses to a line (isUsable is then false). */
function clampRect(rect, bounds) {
  return {
    x0: clip(rect.x0, bounds.x0, bounds.x1), y0: clip(rect.y0, bounds.y0, bounds.y1),
    x1: clip(rect.x1, bounds.x0, bounds.x1), y1: clip(rect.y1, bounds.y0, bounds.y1),
  };
}

/* A frame smaller than a square foot, or flat, is a mis-click, not an area (same rule as the add-in). */
function isUsable(rect) {
  const w = rect.x1 - rect.x0, h = rect.y1 - rect.y0;
  return w > 0 && h > 0 && w * h > 1;
}

/* What is under the point: a corner ('nw' ...), a side ('n' ...), the inside ('move'), or null. tol is in plan units. */
function hitTest(rect, p, tol) {
  const nearX0 = Math.abs(p.x - rect.x0) <= tol, nearX1 = Math.abs(p.x - rect.x1) <= tol;
  const nearY0 = Math.abs(p.y - rect.y0) <= tol, nearY1 = Math.abs(p.y - rect.y1) <= tol;
  const inX = p.x >= rect.x0 - tol && p.x <= rect.x1 + tol, inY = p.y >= rect.y0 - tol && p.y <= rect.y1 + tol;
  if (nearY0 && nearX0) return 'nw';
  if (nearY0 && nearX1) return 'ne';
  if (nearY1 && nearX0) return 'sw';
  if (nearY1 && nearX1) return 'se';
  if (nearY0 && inX) return 'n';
  if (nearY1 && inX) return 's';
  if (nearX1 && inY) return 'e';
  if (nearX0 && inY) return 'w';
  if (p.x > rect.x0 && p.x < rect.x1 && p.y > rect.y0 && p.y < rect.y1) return 'move';
  return null;
}

/* The frame after dragging a handle by (dx, dy). 'move' keeps the size and stops at the plan's edge; the others
   move their own sides, flip if dragged past the opposite side, and stay inside bounds. */
function applyDrag(rect, handle, dx, dy, bounds) {
  if (handle === 'move') {
    const w = rect.x1 - rect.x0, h = rect.y1 - rect.y0;
    const x0 = clip(rect.x0 + dx, bounds.x0, bounds.x1 - w), y0 = clip(rect.y0 + dy, bounds.y0, bounds.y1 - h);
    return { x0, y0, x1: x0 + w, y1: y0 + h };
  }
  let { x0, y0, x1, y1 } = rect;
  if (handle.includes('w')) x0 += dx;
  if (handle.includes('e')) x1 += dx;
  if (handle.includes('n')) y0 += dy;
  if (handle.includes('s')) y1 += dy;
  return clampRect(normaliseRect({ x: x0, y: y0 }, { x: x1, y: y1 }), bounds);
}

/* Plan space to Revit model space: y is negated, so the corners swap. */
function toModelBox(rect) {
  return { xmin: rect.x0, ymin: -rect.y1, xmax: rect.x1, ymax: -rect.y0 };
}

function fromModelBox(box) {
  return { x0: box.xmin, y0: -box.ymax, x1: box.xmax, y1: -box.ymin };
}

if (typeof module === 'object') module.exports = { normaliseRect, clampRect, isUsable, hitTest, applyDrag, toModelBox, fromModelBox };
