const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../js/topview.js');

const bounds = { xmin: 0, xmax: 60, ymin: 0, ymax: 40 };       // Revit feet, model space

test('the picture sits over the plan: x as in Revit, y negated (top edge at -ymax)', () => {
  assert.deepEqual(T.underlayPlacement(bounds), { x: 0, y: -40, width: 60, height: 40 });
});

test('the camera looks straight down at the middle of the plan, sized to its extent in metres', () => {
  const c = T.topCamera(bounds, 0.3048);
  assert.ok(Math.abs(c.width - 60 * 0.3048) < 1e-9 && Math.abs(c.height - 40 * 0.3048) < 1e-9);
  assert.ok(Math.abs(c.cx - 30 * 0.3048) < 1e-9);
  assert.ok(Math.abs(c.cz - -20 * 0.3048) < 1e-9);          // three z = minus model y
});

test('imageSize keeps the plan proportions with the longer side at the maximum', () => {
  assert.deepEqual(T.imageSize(bounds, 2048), { w: 2048, h: 1365 });
  assert.deepEqual(T.imageSize({ xmin: 0, xmax: 10, ymin: 0, ymax: 40 }, 1000), { w: 250, h: 1000 });
});

test('imageSize never returns a zero side for a very thin plan', () => {
  const s = T.imageSize({ xmin: 0, xmax: 100000, ymin: 0, ymax: 1 }, 2048);
  assert.ok(s.w >= 1 && s.h >= 1);
});

test('everything above the cut is clipped away: level height plus the cut height', () => {
  assert.equal(T.clipHeight(3.9624, 2.6), 3.9624 + 2.6);
  assert.equal(T.clipHeight(0, T.CUT_M), T.CUT_M);
  assert.equal(T.CUT_M, 2.6);
});

test('roofs and ceilings are left out of the top view', () => {
  assert.equal(T.hiddenTypes().has('roof'), true);
  assert.equal(T.hiddenTypes().has('ceiling'), true);
  assert.equal(T.hiddenTypes().has('wall'), false);
});

test('a plan with no bounds gives no picture', () => {
  assert.equal(T.underlayPlacement(null), null);
  assert.equal(T.topCamera(null, 1), null);
  assert.equal(T.imageSize(null, 2048), null);
});
