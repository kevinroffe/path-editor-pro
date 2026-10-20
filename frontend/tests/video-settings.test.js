const test = require('node:test');
const assert = require('node:assert/strict');
const V = require('../js/video-settings.js');

const mapStorage = () => {
  const m = new Map();
  return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
};
const throwingStorage = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };

test('cleanVideo of nothing is the default', () => assert.deepEqual(V.cleanVideo(null), V.defaultVideo()));

test('cleanVideo repairs bad values', () => {
  const v = V.cleanVideo({ theme: 'x', volume: 3, name: '  A  ', fades: [{ outM: 5, inM: 2 }, { outM: 1, inM: 4 }] });
  assert.equal(v.theme, 'premium-lobby');
  assert.equal(v.volume, 1);
  assert.equal(v.name, 'A');
  assert.deepEqual(v.fades, [{ outM: 1, inM: 4 }]);
});

test('acceptLogo refuses a JPEG', () => assert.equal(V.acceptLogo({ type: 'image/jpeg', size: 10 }), 'Use a PNG or SVG logo.'));

test('acceptLogo refuses a big PNG', () =>
  assert.equal(V.acceptLogo({ type: 'image/png', size: 2_000_000 }), 'That logo is over 1.5 MB. Use a smaller file.'));

test('acceptLogo takes a small SVG', () => assert.equal(V.acceptLogo({ type: 'image/svg+xml', size: 3000 }), null));

test('brand prefs default when storage throws', () => {
  assert.deepEqual(V.loadBrandPrefs(throwingStorage), { logo: null, logoName: '', colour: 'charcoal', theme: 'premium-lobby' });
  assert.doesNotThrow(() => V.saveBrandPrefs(throwingStorage, { logo: 'data:x', logoName: 'a.png', colour: 'teal', theme: 'bright-leasing' }));
});

test('brand prefs round-trip', () => {
  const s = mapStorage(), prefs = { logo: 'data:image/png;base64,AA', logoName: 'a.png', colour: 'teal', theme: 'bright-leasing' };
  V.saveBrandPrefs(s, prefs);
  assert.deepEqual(V.loadBrandPrefs(s), prefs);
});
