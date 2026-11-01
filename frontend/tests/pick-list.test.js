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

test('a snapshot looks at the room, or on along the walk when standing inside a walk-in area next to its label', () => {
  const room = { x: 0, y: 0, stop: { look_at: [0, 300], walk_in: false } };
  const near = { x: 0, y: 0, stop: { look_at: [20, 30], walk_in: true } };
  const far = { x: 0, y: 0, stop: { look_at: [0, 400], walk_in: true } };
  assert.deepEqual(P.stripTarget([room, { x: 500, y: 0 }], 0, 150), [0, 300]);
  assert.deepEqual(P.stripTarget([near, { x: 10, y: 0 }, { x: 500, y: 0 }], 0, 150), [500, 0]);
  assert.deepEqual(P.stripTarget([far, { x: 500, y: 0 }], 0, 150), [0, 400]);
  assert.deepEqual(P.stripTarget([{ x: -500, y: 0 }, near], 1, 150), [500, 0]);   // last point: keep walking the same way
});
