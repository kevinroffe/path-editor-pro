const test = require('node:test');
const assert = require('node:assert/strict');
const { createSelection } = require('../js/selection.js');

test('select notifies subscribers once per change, not for the same id again', () => {
  const sel = createSelection();
  const seen = [];
  sel.subscribe(id => seen.push(id));
  sel.select('kf:2');
  sel.select('kf:2');
  sel.select('kf:3');
  sel.select(null);
  assert.deepEqual(seen, ['kf:2', 'kf:3', null]);
  assert.equal(sel.get(), null);
});

test('unsubscribe stops calls', () => {
  const sel = createSelection();
  let n = 0;
  const off = sel.subscribe(() => n++);
  sel.select('kf:1');
  off();
  sel.select('kf:2');
  assert.equal(n, 1);
  assert.equal(sel.get(), 'kf:2');
});
