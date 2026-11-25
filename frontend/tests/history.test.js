const test = require('node:test');
const assert = require('node:assert/strict');
const { createHistory } = require('../js/history.js');

test('undo goes back one change and redo forward again', () => {
  const h = createHistory();
  h.reset('a');
  h.record('b');
  h.record('c');
  assert.equal(h.undo(), 'b');
  assert.equal(h.undo(), 'a');
  assert.equal(h.undo(), null);
  assert.equal(h.redo(), 'b');
  assert.equal(h.redo(), 'c');
  assert.equal(h.redo(), null);
});

test('recording the same state twice is one step', () => {
  const h = createHistory();
  h.reset('a');
  assert.equal(h.record('a'), false);
  assert.equal(h.record('b'), true);
  assert.equal(h.record('b'), false);
  assert.equal(h.undo(), 'a');
  assert.equal(h.canUndo(), false);
});

test('a new change after an undo drops what could be redone', () => {
  const h = createHistory();
  h.reset('a');
  h.record('b');
  h.undo();
  h.record('x');
  assert.equal(h.canRedo(), false);
  assert.equal(h.undo(), 'a');
});

test('history keeps at most the limit of steps back', () => {
  const h = createHistory(3);
  h.reset('0');
  ['1', '2', '3', '4', '5'].forEach(s => h.record(s));
  assert.equal(h.undo(), '4');
  assert.equal(h.undo(), '3');
  assert.equal(h.undo(), '2');
  assert.equal(h.undo(), null);
});

test('reset starts a fresh history at the given state', () => {
  const h = createHistory();
  h.reset('a');
  h.record('b');
  h.reset('z');
  assert.equal(h.canUndo(), false);
  assert.equal(h.canRedo(), false);
  assert.equal(h.record('z'), false);
});
