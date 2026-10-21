const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../js/music.js');
const { THEMES } = require('../js/video-settings.js');

const ROOT = path.join(__dirname, '..', '..');

test('trackOffset follows the track, then loops with a 2 s crossfade', () => {
  assert.equal(M.LOOP_CROSSFADE_S, 2);
  assert.equal(M.trackOffset(10, 96), 10);
  assert.equal(M.trackOffset(93, 96), 93);
  assert.equal(M.trackOffset(95, 96), 1, 'second pass began at 94 s and is crossfading');
  assert.equal(M.trackOffset(96, 96), 2);
  assert.equal(M.trackOffset(300, 96), 300 % 94);
});

test('every track is a bundled file with a title, artist and length', () => {
  for (const [id, t] of Object.entries(M.TRACKS)) {
    assert.match(t.file, /^frontend\/audio\/[\w-]+\.mp3$/, id);
    assert.ok(fs.existsSync(path.join(ROOT, t.file)), `${t.file} is on disk`);
    assert.ok(t.title && t.artist, id);
    assert.ok(t.durationS > 0, id);
  }
});

test('one track per theme', () => {
  assert.deepEqual(Object.keys(M.TRACKS), THEMES.map(t => t.id));
});

test('theme cards name the track and artist', () => {
  for (const t of THEMES) assert.equal(t.sub, `${M.TRACKS[t.id].title} — ${M.TRACKS[t.id].artist}`);
});

test('a short video plays one pass from the requested second', () => {
  assert.deepEqual(M.loopPasses(10, 60, 96), [{ at: 0, offset: 10, fadeIn: false, fadeOut: false }]);
});

test('a long video loops, each pass crossfading into the next', () => {
  assert.deepEqual(M.loopPasses(0, 200, 96), [
    { at: 0, offset: 0, fadeIn: false, fadeOut: true },
    { at: 94, offset: 0, fadeIn: true, fadeOut: true },
    { at: 188, offset: 0, fadeIn: true, fadeOut: false },
  ]);
});

test('starting inside a crossfade plays both passes', () => {
  const passes = M.loopPasses(95, 150, 96);
  assert.deepEqual(passes, [
    { at: 0, offset: 95, fadeIn: false, fadeOut: true },
    { at: 94, offset: 1, fadeIn: true, fadeOut: false },
  ]);
  assert.equal(passes.at(-1).offset, M.trackOffset(95, 96));
});

function fakeContext() {
  const param = () => ({ value: 0, setTargetAtTime() {}, cancelScheduledValues() {}, setValueAtTime() {}, linearRampToValueAtTime() {} });
  const ctx = {
    currentTime: 0, state: 'running', destination: {}, starts: [],
    createGain: () => ({ gain: param(), connect: x => x }),
    createBufferSource: () => ({ connect: x => x, stop() {}, start: (...a) => ctx.starts.push(a) }),
  };
  return ctx;
}

test('prime unlocks audio once without playing anything', () => {
  let made = 0;
  const ctx = fakeContext(), player = M.createMusicPlayer(() => { made++; return ctx; });
  player.prime(); player.prime();
  assert.equal(made, 1);
  assert.equal(ctx.starts.length, 0);
  assert.equal(player.playing, false);
});
