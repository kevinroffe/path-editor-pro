const test = require('node:test');
const assert = require('node:assert/strict');
const P = require('../js/pick-list.js');

const wp = (room_id, extra = {}) => ({ x: 0, y: 0, stop: room_id ? { room_id, dwell_s: 2, pan: false, ...extra } : null });

test('carry keeps dwell and pan by room', () => {
  const out = P.carryStopSettings([wp('a', { dwell_s: 5, pan: true })], [wp('b'), wp('a')]);
  assert.deepEqual(out.map(w => [w.stop.room_id, w.stop.dwell_s, w.stop.pan]), [['b', 2, false], ['a', 5, true]]);
});

test('carry does not mutate', () => {
  const next = [wp('a')];
  P.carryStopSettings([wp('a', { dwell_s: 9 })], next);
  assert.equal(next[0].stop.dwell_s, 2);
});

test('carry caps pans at 2', () => {
  const prev = ['a', 'b', 'c'].map(id => wp(id, { pan: true }));
  assert.equal(P.carryStopSettings(prev, ['a', 'b', 'c'].map(id => wp(id))).filter(w => w.stop.pan).length, 2);
});

test('pick list from stops', () => assert.deepEqual(P.pickListFromWaypoints([wp(null), wp('a'), wp('b'), wp('a')]), ['a', 'b']));

test('quick add offices in plan order, no repeats', () => {
  const rooms = [{ id: 'k', type: 'Kitchen' }, { id: 'o1', type: 'Office - Non Receiving Guests' }, { id: 'o2', type: 'Office' }];
  assert.deepEqual(P.quickAdd(rooms, ['o2'], 'offices'), ['o2', 'o1']);
});

test('third pan refused, unpan always allowed', () => {
  const w = [wp('a', { pan: true }), wp('b', { pan: true }), wp('c')];
  assert.equal(P.canSetPan(w, 2, true), false);
  assert.equal(P.canSetPan(w, 0, false), true);
});
