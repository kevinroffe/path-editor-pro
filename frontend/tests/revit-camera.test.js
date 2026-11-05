const test = require('node:test');
const assert = require('node:assert/strict');
const R = require('../js/revit-camera.js');

test('the first pose goes out at once', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  assert.deepEqual(t.push({ n: 1 }), { n: 1 });
});

test('poses that arrive inside the interval are held, and only the latest is kept', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  t.push({ n: 1 });
  now = 10; assert.equal(t.push({ n: 2 }), null);
  now = 20; assert.equal(t.push({ n: 3 }), null);
  now = 30; assert.equal(t.take(), null);               // not due yet
  now = 80; assert.deepEqual(t.take(), { n: 3 });         // the latest, once
  assert.equal(t.take(), null);
});

test('after the interval the next pose goes out immediately', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  t.push({ n: 1 });
  now = 100;
  assert.deepEqual(t.push({ n: 2 }), { n: 2 });
});

test('a held pose is dropped when a newer one goes out directly', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  t.push({ n: 1 });
  now = 10; t.push({ n: 2 });                             // held
  now = 200; assert.deepEqual(t.push({ n: 3 }), { n: 3 }); // sent directly
  now = 400; assert.equal(t.take(), null);                // the held n=2 is not sent late
});

test('cameraMessage carries the plan position, yaw and the level height in feet', () => {
  assert.deepEqual(R.cameraMessage({ x: 10, y: -20, yaw: 45 }, 13), { type: 'camera', x: 10, y: -20, yaw: 45, elevation: 13 });
  assert.deepEqual(R.cameraMessage({ x: 1, y: 2, yaw: 0 }, undefined), { type: 'camera', x: 1, y: 2, yaw: 0, elevation: 0 });
});

test('frameAt interpolates the preview frames and clamps t', () => {
  const frames = [{ x: 0, y: 0, yaw: 350 }, { x: 10, y: 0, yaw: 10 }];
  const mid = R.frameAt(frames, 0.5);
  assert.equal(mid.x, 5);
  assert.ok(Math.abs(((mid.yaw % 360) + 360) % 360) < 1e-9 || Math.abs(((mid.yaw % 360) + 360) % 360 - 360) < 1e-9);   // the short way round: 0
  assert.equal(R.frameAt(frames, -3).x, 0);
  assert.equal(R.frameAt(frames, 9).x, 10);
  assert.equal(R.frameAt([], 0.5), null);
  assert.equal(R.frameAt([{ x: 1, y: 2, yaw: 3 }], 0.5).x, 1);
});

test('a pose equal to the last one sent is not sent again (a paused video must not keep editing Revit)', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  assert.deepEqual(t.push({ x: 1, y: 2, yaw: 3, elevation: 0 }), { x: 1, y: 2, yaw: 3, elevation: 0 });
  now = 500; assert.equal(t.push({ x: 1, y: 2, yaw: 3, elevation: 0 }), null);
  now = 900; assert.equal(t.take(), null);
  now = 1000; assert.deepEqual(t.push({ x: 1, y: 2, yaw: 4, elevation: 0 }), { x: 1, y: 2, yaw: 4, elevation: 0 });
});

test('a held pose that turns out equal to the last sent one is dropped', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  t.push({ x: 1, y: 2, yaw: 3, elevation: 0 });
  now = 10; t.push({ x: 5, y: 5, yaw: 5, elevation: 0 });       // held
  now = 20; t.push({ x: 1, y: 2, yaw: 3, elevation: 0 });       // back where it was: nothing to send
  now = 200; assert.equal(t.take(), null);
});

test('reset makes the next pose go out even if it equals the last one (a new preview start)', () => {
  let now = 0;
  const t = R.makeThrottle(70, () => now);
  t.push({ x: 1, y: 2, yaw: 3, elevation: 0 });
  t.reset();
  now = 500; assert.deepEqual(t.push({ x: 1, y: 2, yaw: 3, elevation: 0 }), { x: 1, y: 2, yaw: 3, elevation: 0 });
});

test('the Revit camera is only allowed for a model that came from Revit, inside Revit', () => {
  assert.equal(R.cameraAllowed('revit', true), true);
  assert.equal(R.cameraAllowed('json', true), false);
  assert.equal(R.cameraAllowed('revit', false), false);
  assert.equal(R.cameraAllowed(undefined, true), false);
});
