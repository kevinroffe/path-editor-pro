const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../js/music.js');

const BPM = { 'premium-lobby': 70, 'modern-workspace': 100, 'bright-leasing': 118, 'cinematic-reveal': 64 };

test('midiToHz(69) is concert A', () => assert.equal(M.midiToHz(69), 440));

for (const [id, bpm] of Object.entries(BPM)) {
  test(`${id} is ${bpm} bpm and loops cleanly`, () => {
    const p = M.themePattern(id);
    assert.equal(p.bpm, bpm);
    assert.ok(p.notes.length > 0);
    for (const n of p.notes) {
      assert.ok(n.beat >= 0 && n.beat + n.beats <= p.bars * 4, `note ${JSON.stringify(n)} runs past the loop`);
      assert.ok(n.vel > 0 && n.vel <= 1);
      assert.ok(['pad', 'keys', 'pulse', 'bass'].includes(n.voice));
    }
  });
}

test('the four themes are different', () => {
  const sigs = Object.keys(BPM).map(id => JSON.stringify(M.themePattern(id).notes));
  assert.equal(new Set(sigs).size, 4);
});

test('cinematic reveal builds towards the end, others stay level', () => {
  assert.equal(M.intensityAt('cinematic-reveal', 0, 60), 0.35);
  assert.equal(M.intensityAt('cinematic-reveal', 60, 60), 1);
  assert.equal(M.intensityAt('bright-leasing', 0, 60), 1);
});

function fakeContext() {
  const param = () => ({ value: 0, setTargetAtTime() {}, cancelScheduledValues() {}, setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} });
  const node = extra => ({ connect: x => x, ...extra });
  const ctx = {
    currentTime: 0, state: 'running', destination: {}, starts: [],
    createGain: () => node({ gain: param() }),
    createBiquadFilter: () => node({ type: '', frequency: param() }),
    createOscillator: () => {
      const o = node({ type: '', frequency: param(), stop() {}, start: when => ctx.starts.push({ when, hz: o.frequency.value }) });
      return o;
    },
  };
  return ctx;
}

test('player schedules the first chord straight away and stops cleanly', () => {
  const ctx = fakeContext(), player = M.createMusicPlayer(() => ctx);
  player.start(0, 30);
  player.stop();
  const first = ctx.starts.filter(s => Math.abs(s.when - 0.05) < 1e-6).map(s => Math.round(s.hz));
  assert.ok(first.includes(Math.round(M.midiToHz(60))), 'C4 pad note at the start');
  assert.ok(first.includes(Math.round(M.midiToHz(36))), 'bass root at the start');
  assert.equal(player.playing, false);
});

test('starting mid-video picks up the right bar', () => {
  const ctx = fakeContext(), player = M.createMusicPlayer(() => ctx);
  player.start(4 * 60 / 70, 30); // bar 2 of Premium lobby: A minor
  player.stop();
  const hz = ctx.starts.map(s => Math.round(s.hz));
  assert.ok(hz.includes(Math.round(M.midiToHz(57))));
  assert.ok(!hz.includes(Math.round(M.midiToHz(71))), 'no bar-1 chord tones');
});
