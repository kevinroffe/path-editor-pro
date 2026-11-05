const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../js/plan-view.js');

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test('viewCone has the apex first and its two far corners at yaw plus and minus half the field of view', () => {
  const [apex, a, b] = P.viewCone(0, 0, 0, 90, 10);
  assert.deepEqual(apex, [0, 0]);
  near(a[0], 10 * Math.cos(-Math.PI / 4)); near(a[1], 10 * Math.sin(-Math.PI / 4));
  near(b[0], 10 * Math.cos(Math.PI / 4)); near(b[1], 10 * Math.sin(Math.PI / 4));
});

test('yaw 0 looks along +x and yaw 90 along +y in plan space', () => {
  const east = P.viewCone(5, 5, 0, 60, 4);
  assert.ok(east[1][0] > 5 && east[2][0] > 5);
  const south = P.viewCone(5, 5, 90, 60, 4);
  assert.ok(south[1][1] > 5 && south[2][1] > 5);
});

test('the cone is centred on the apex position', () => {
  const [apex] = P.viewCone(12.5, -3, 33, 70, 2);
  assert.deepEqual(apex, [12.5, -3]);
});

test('a missing or silly field of view gives a narrow default cone rather than a broken one', () => {
  const [, a, b] = P.viewCone(0, 0, 0, undefined, 10);
  assert.ok(Number.isFinite(a[0]) && Number.isFinite(b[1]));
  assert.ok(b[1] - a[1] > 0);                         // it has some width
  const [, c, d] = P.viewCone(0, 0, 0, 400, 10);
  assert.ok(Number.isFinite(c[0]) && Number.isFinite(d[1]));
});

test('pauseKeyframes lists only the keyframes where the camera stands still', () => {
  const plan = { keyframes: [{ x: 0, y: 0, still_s: 0 }, { x: 5, y: 0, still_s: 2 }, { x: 9, y: 1, still_s: 0.5 }, { x: 12, y: 1 }] };
  assert.deepEqual(P.pauseKeyframes(plan).map(k => k.x), [5, 9]);
  assert.deepEqual(P.pauseKeyframes(null), []);
  assert.deepEqual(P.pauseKeyframes({}), []);
});

test('nearestFrame finds the closest preview frame, and null without frames', () => {
  const frames = [{ x: 0, y: 0, yaw: 10 }, { x: 10, y: 0, yaw: 20 }, { x: 20, y: 0, yaw: 30 }];
  assert.equal(P.nearestFrame(frames, 11, 1).yaw, 20);
  assert.equal(P.nearestFrame([], 1, 1), null);
  assert.equal(P.nearestFrame(undefined, 1, 1), null);
});

test('coneLength scales with the plan so a cone is readable on a large or small plan', () => {
  assert.ok(P.coneLength({ xmin: 0, xmax: 100, ymin: 0, ymax: 50 }) > P.coneLength({ xmin: 0, xmax: 10, ymin: 0, ymax: 5 }));
  assert.ok(P.coneLength(null) > 0);
});
