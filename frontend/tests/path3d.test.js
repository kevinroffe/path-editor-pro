const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../js/path3d.js');

const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const nearAll = (a, b) => a.forEach((v, i) => near(v, b[i]));

test('routeToWorld scales feet to metres, turns display y back into model y and adds eye height', () => {
  const out = P.routeToWorld([[10, -20, 0, '', null], [50, -20]], 0.3048, 1.57);
  nearAll(out[0], [3.048, 6.096, 1.57]);
  nearAll(out[1], [15.24, 6.096, 1.57]);
  nearAll(P.routeToWorld([[0, 0]], 1, 1.57, 3)[0], [0, 0, 4.57]);   // level elevation is added
});

test('coneParams puts the base corners lengthM along the yaw, spread by the field of view', () => {
  const { apex, baseCorners } = P.coneParams([0, 0, 1.57], 0, 90, 2);
  assert.deepEqual(apex, [0, 0, 1.57]);
  assert.equal(baseCorners.length, 4);
  baseCorners.forEach(c => { near(c[0], 2); near(Math.abs(c[1]), 2); });   // tan(45°) * 2 m to each side
  near(baseCorners.reduce((s, c) => s + c[2], 0) / 4, 1.57);                // centred on the eye height
});

test('coneParams yaw is display-space degrees: 90 points toward -y in model space', () => {
  const { baseCorners } = P.coneParams([0, 0, 0], 90, 90, 1);
  baseCorners.forEach(c => near(c[1], -1));
});

test('poseAt interpolates frames and the yaw takes the short way round', () => {
  const frames = [{ t: 0, x: 0, y: 0, yaw: 350, fov: 90 }, { t: 1, x: 10, y: 0, yaw: 10, fov: 90 }];
  const mid = P.poseAt(frames, 0.5, 1, 1.57);
  nearAll(mid.position, [5, 0, 1.57]);
  nearAll(mid.lookAt, [6, 0, 1.57]);      // yaw 0: one metre ahead along +x
  assert.equal(mid.fovDeg, 90);
  nearAll(P.poseAt(frames, 0, 1, 1.57).position, [0, 0, 1.57]);
  nearAll(P.poseAt(frames, 1, 1, 1.57).position, [10, 0, 1.57]);
});

test('poseAt clamps outside 0..1', () => {
  const frames = [{ t: 0, x: 0, y: 0, yaw: 0, fov: 90 }, { t: 1, x: 10, y: 0, yaw: 0, fov: 90 }];
  nearAll(P.poseAt(frames, -3, 1, 1.5).position, [0, 0, 1.5]);
  nearAll(P.poseAt(frames, 9, 1, 1.5).position, [10, 0, 1.5]);
});

test('floorHit finds the floor point of a downward ray, and null otherwise', () => {
  assert.deepEqual(P.floorHit([0, 0, 10], [1, 0, -1], 0), [10, 0]);
  assert.equal(P.floorHit([0, 0, 10], [1, 0, 1], 0), null);     // pointing up
  assert.equal(P.floorHit([0, 0, 10], [1, 0, 0], 0), null);     // parallel to the floor
});
