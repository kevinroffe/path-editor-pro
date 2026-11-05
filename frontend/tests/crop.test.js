const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../js/crop.js');

const bounds = { x0: 0, y0: -40, x1: 60, y1: 0 };       // display space: y is negated model y

test('normaliseRect puts the corners in order whatever way the user dragged', () => {
  assert.deepEqual(C.normaliseRect({ x: 10, y: -5 }, { x: 2, y: -30 }), { x0: 2, y0: -30, x1: 10, y1: -5 });
});

test('clampRect clips a frame that sticks out of the plan', () => {
  assert.deepEqual(C.clampRect({ x0: -10, y0: -50, x1: 30, y1: -10 }, bounds), { x0: 0, y0: -40, x1: 30, y1: -10 });
  assert.deepEqual(C.clampRect({ x0: 5, y0: -30, x1: 20, y1: -10 }, bounds), { x0: 5, y0: -30, x1: 20, y1: -10 });
});

test('a frame outside the plan clamps to something unusable', () => {
  assert.equal(C.isUsable(C.clampRect({ x0: 100, y0: 100, x1: 120, y1: 120 }, bounds)), false);
});

test('isUsable rejects tiny and flat frames', () => {
  assert.equal(C.isUsable({ x0: 0, y0: 0, x1: 0.5, y1: 0.5 }), false);
  assert.equal(C.isUsable({ x0: 0, y0: 0, x1: 50, y1: 0 }), false);
  assert.equal(C.isUsable({ x0: 0, y0: 0, x1: 10, y1: 10 }), true);
});

test('hitTest finds corners, edges and the inside, and null far away', () => {
  const r = { x0: 10, y0: -30, x1: 40, y1: -10 };
  assert.equal(C.hitTest(r, { x: 10, y: -30 }, 1), 'nw');
  assert.equal(C.hitTest(r, { x: 40, y: -30 }, 1), 'ne');
  assert.equal(C.hitTest(r, { x: 10, y: -10 }, 1), 'sw');
  assert.equal(C.hitTest(r, { x: 40, y: -10 }, 1), 'se');
  assert.equal(C.hitTest(r, { x: 25, y: -30 }, 1), 'n');
  assert.equal(C.hitTest(r, { x: 25, y: -10 }, 1), 's');
  assert.equal(C.hitTest(r, { x: 40, y: -20 }, 1), 'e');
  assert.equal(C.hitTest(r, { x: 10, y: -20 }, 1), 'w');
  assert.equal(C.hitTest(r, { x: 25, y: -20 }, 1), 'move');
  assert.equal(C.hitTest(r, { x: 55, y: -5 }, 1), null);
});

test('hitTest tolerance widens the grab zone', () => {
  const r = { x0: 10, y0: -30, x1: 40, y1: -10 };
  assert.equal(C.hitTest(r, { x: 11.5, y: -29 }, 2), 'nw');
  assert.equal(C.hitTest(r, { x: 11.5, y: -29 }, 0.5), 'move');
});

test('dragging a corner resizes, dragging the inside moves without resizing', () => {
  const r = { x0: 10, y0: -30, x1: 40, y1: -10 };
  assert.deepEqual(C.applyDrag(r, 'se', 5, -3, bounds), { x0: 10, y0: -30, x1: 45, y1: -13 });
  assert.deepEqual(C.applyDrag(r, 'move', 5, 3, bounds), { x0: 15, y0: -27, x1: 45, y1: -7 });
  assert.deepEqual(C.applyDrag(r, 'e', -10, 99, bounds), { x0: 10, y0: -30, x1: 30, y1: -10 });   // an edge handle moves one side only
});

test('moving stops at the edge of the plan instead of shrinking the frame', () => {
  const r = { x0: 10, y0: -30, x1: 40, y1: -10 };
  assert.deepEqual(C.applyDrag(r, 'move', 100, 100, bounds), { x0: 30, y0: -20, x1: 60, y1: 0 });
});

test('dragging a side past the opposite side flips the frame', () => {
  const r = { x0: 10, y0: -30, x1: 40, y1: -10 };
  assert.deepEqual(C.applyDrag(r, 'e', -50, 0, bounds), { x0: 0, y0: -30, x1: 10, y1: -10 });
});

test('toModelBox turns display y back into model y and orders the corners', () => {
  assert.deepEqual(C.toModelBox({ x0: 10, y0: -30, x1: 40, y1: -10 }), { xmin: 10, ymin: 10, xmax: 40, ymax: 30 });
});

test('fromModelBox is the inverse', () => {
  const rect = { x0: 10, y0: -30, x1: 40, y1: -10 };
  assert.deepEqual(C.fromModelBox(C.toModelBox(rect)), rect);
});

test('a plain click that makes no usable frame keeps the frame the user had', () => {
  const before = { x0: 0, y0: -25, x1: 40, y1: 0 };
  assert.deepEqual(C.keepIfUsable({ x0: 12, y0: -8, x1: 12, y1: -8 }, before), before);           // a click: zero area
  const dragged = { x0: 5, y0: -20, x1: 25, y1: -5 };
  assert.deepEqual(C.keepIfUsable(dragged, before), dragged);                                       // a real drag wins
});
