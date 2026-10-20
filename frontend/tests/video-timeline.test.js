const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../js/video-timeline.js');

const frames = Array.from({ length: 11 }, (_, i) => ({ x: i, y: 0 }));
const dists = T.routeDistances(frames, 1);
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

test('routeDistances is cumulative metres', () => assert.deepEqual(dists, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]));

test('walkTimeAtDistance interpolates', () => assert.equal(T.walkTimeAtDistance(dists, 10, 2.5), 2.5));

test('no fades: total is cards plus walk', () => assert.equal(T.buildTimeline({ dists, walkSeconds: 10, fades: [] }).total, 16));

test('a fade skips the walk between its points', () => {
  const tl = T.buildTimeline({ dists, walkSeconds: 10, fades: [{ outM: 2, inM: 6 }] });
  near(tl.total, 12.8);
  assert.deepEqual(tl.blocks.map(b => b.kind), ['intro', 'walk', 'fade', 'walk', 'outro']);
});

test('mid-fade is black, its edges are not', () => {
  const tl = T.buildTimeline({ dists, walkSeconds: 10, fades: [{ outM: 2, inM: 6 }] });
  assert.equal(T.sampleTimeline(tl, 5.4).black, 1);
  assert.equal(T.sampleTimeline(tl, 5.0).black, 0);
  near(T.sampleTimeline(tl, 5.8).walkS, 6);
});

test('cards report their card', () => {
  const tl = T.buildTimeline({ dists, walkSeconds: 10, fades: [] });
  assert.equal(T.sampleTimeline(tl, 1).card, 'intro');
  assert.equal(T.sampleTimeline(tl, 15).card, 'outro');
  assert.equal(T.sampleTimeline(tl, 4).walkS, 1);
});

test('makeFade refuses a backwards fade', () => assert.ok(T.makeFade(6, 2, [], 10).error));

test('makeFade refuses an overlapping fade', () => assert.ok(T.makeFade(5, 8, [{ outM: 2, inM: 6 }], 10).error));

test('makeFade accepts a forward fade', () => assert.deepEqual(T.makeFade(2, 6, [], 10).fade, { outM: 2, inM: 6 }));

test('pruneFades drops fades past the end', () =>
  assert.deepEqual(T.pruneFades([{ outM: 2, inM: 6 }, { outM: 7, inM: 12 }], 10), [{ outM: 2, inM: 6 }]));

test('musicGain fades in over the intro and out over the last 2 s', () => {
  assert.equal(T.musicGain(0, 16), 0);
  assert.equal(T.musicGain(3, 16), 1);
  assert.equal(T.musicGain(15, 16), 0.5);
  assert.equal(T.musicGain(16, 16), 0);
});

test('projectToRoute snaps a point to route metres', () => near(T.projectToRoute(frames, dists, 1, 4.2, 3), 4.2));
