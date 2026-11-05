const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../js/host.js');

test('hostMode reads ?host=revit and defaults to browser', () => {
  assert.equal(H.hostMode('?host=revit'), 'revit');
  assert.equal(H.hostMode('?key=abc&host=revit'), 'revit');
  assert.equal(H.hostMode(''), 'browser');
  assert.equal(H.hostMode('?host=other'), 'browser');
});

test('engineKey reads ?key= or is null', () => {
  assert.equal(H.engineKey('?key=abc'), 'abc');
  assert.equal(H.engineKey('?host=revit'), null);
});

test('authHeaders carries X-Qbiq-Key only when a key exists', () => {
  assert.deepEqual(H.authHeaders('?key=abc'), { 'X-Qbiq-Key': 'abc' });
  assert.deepEqual(H.authHeaders(''), {});
});

test('handleHostMessage dispatches known types and ignores unknown ones without throwing', () => {
  const seen = [];
  const handlers = { modelLoaded: (m) => seen.push(m.type), modelRefreshed: (m) => seen.push(m.type) };
  assert.equal(H.handleHostMessage({ type: 'modelLoaded' }, handlers), true);
  assert.equal(H.handleHostMessage({ type: 'nonsense' }, handlers), false);
  assert.equal(H.handleHostMessage({ type: 'nonsense' }, {}), false);
  assert.equal(H.handleHostMessage(null, handlers), false);
  assert.equal(H.handleHostMessage({ type: 'toString' }, handlers), false);   // inherited names are not handlers
  assert.deepEqual(seen, ['modelLoaded']);
});

test('postToHost is a no-op outside WebView2', () => {
  assert.doesNotThrow(() => H.postToHost({ type: 'x' }));
});
