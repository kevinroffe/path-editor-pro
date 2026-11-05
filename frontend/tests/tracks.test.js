const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../js/tracks.js');
const V = require('../js/video-timeline.js');

const kf = (t_s, x, still_s = 0, yaw = 0) => ({ t_s, x, y: 0, yaw, hour: null, cut_after: false, still_s });
const plan = { units_to_metres: 1, keyframes: [kf(0, 0), kf(4, 4, 2), kf(6, 4), kf(10, 10)] };

test('lanes come in the fixed order with stable ids', () => {
  const t = T.buildTracks({ plan, fades: [], music: null });
  assert.deepEqual(t.lanes.map(l => l.id), ['video', 'camera', 'lookat', 'pauses', 'music']);
});

test('durationS is the last keyframe time plus intro and outro', () => {
  const t = T.buildTracks({ plan, fades: [], music: null });
  assert.equal(t.durationS, V.INTRO_S + 10 + V.OUTRO_S);
});

test('camera lane has one marker per keyframe at its timeline second, ids kf:<index>', () => {
  const cam = T.buildTracks({ plan, fades: [], music: null }).lanes[1];
  assert.deepEqual(cam.clips.map(c => c.id), ['kf:0', 'kf:1', 'kf:2', 'kf:3']);
  assert.deepEqual(cam.clips.map(c => c.startS), [0, 4, 6, 10].map(s => s + V.INTRO_S));
  assert.ok(cam.clips.every(c => c.startS === c.endS));
});

test('a keyframe with still_s 2 yields a 2 second pause clip', () => {
  const pauses = T.buildTracks({ plan, fades: [], music: null }).lanes[3];
  assert.equal(pauses.clips.length, 1);
  assert.equal(pauses.clips[0].id, 'pause:1');
  assert.equal(pauses.clips[0].endS - pauses.clips[0].startS, 2);
});

test('look-at lane has one clip between each pair of keyframes', () => {
  const look = T.buildTracks({ plan, fades: [], music: null }).lanes[2];
  assert.equal(look.clips.length, 3);
  assert.equal(look.clips[0].startS, V.INTRO_S);
  assert.equal(look.clips[2].endS, V.INTRO_S + 10);
});

test('video lane shows intro, walk, outro and any fade', () => {
  const plain = T.buildTracks({ plan, fades: [], music: null }).lanes[0].clips.map(c => c.kind);
  assert.deepEqual(plain, ['intro', 'walk', 'outro']);
  const faded = T.buildTracks({ plan, fades: [{ outM: 1, inM: 3 }], music: null }).lanes[0].clips.map(c => c.kind);
  assert.ok(faded.includes('fade'));
});

test('music lane spans the whole video, or is empty without a track', () => {
  const withMusic = T.buildTracks({ plan, fades: [], music: { id: 'premium-lobby' } });
  assert.equal(withMusic.lanes[4].clips.length, 1);
  assert.equal(withMusic.lanes[4].clips[0].endS, withMusic.durationS);
  assert.equal(T.buildTracks({ plan, fades: [], music: null }).lanes[4].clips.length, 0);
});
