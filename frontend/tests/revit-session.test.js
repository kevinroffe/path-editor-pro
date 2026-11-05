const test = require('node:test');
const assert = require('node:assert/strict');
const S = require('../js/revit-session.js');

const freshState = () => ({ tourRooms: ['a', 'b'], routeHandEdited: true, entrance: [1, 2], step: 3, waypoints: [{ x: 1, y: 2 }] });

test('a refresh keeps the tour picks, hand-edit flag, entrance, step and points', () => {
  const state = freshState();
  const snap = S.captureSession(state);
  Object.assign(state, { tourRooms: [], routeHandEdited: false, entrance: null, step: 2, waypoints: [] });   // what applyFloorPlan resets
  const step = S.restoreSession(state, snap);
  assert.deepEqual(state.tourRooms, ['a', 'b']);
  assert.equal(state.routeHandEdited, true);
  assert.deepEqual(state.entrance, [1, 2]);
  assert.deepEqual(state.waypoints, [{ x: 1, y: 2 }]);
  assert.equal(step, 3);
});

test('the snapshot is not changed by later edits to the live state', () => {
  const state = freshState();
  const snap = S.captureSession(state);
  state.tourRooms.push('c');
  assert.deepEqual(snap.tourRooms, ['a', 'b']);
});

test('bannerMessage is null when nothing is wrong', () => {
  assert.equal(S.bannerMessage([], []), null);
  assert.equal(S.bannerMessage(undefined, undefined), null);
});

test('bannerMessage counts broken rooms by problem', () => {
  const msg = S.bannerMessage([{ problem: 'unplaced' }, { problem: 'unplaced' }, { problem: 'zero_area' }], []);
  assert.match(msg, /3 Revit rooms look broken/);
  assert.match(msg, /2 unplaced/);
  assert.match(msg, /1 zero area/);
});

test('bannerMessage explains a level with no corridor or no rooms', () => {
  assert.match(S.bannerMessage([], ['no_corridor']), /no corridor/i);
  assert.match(S.bannerMessage([], ['no_rooms']), /no placed rooms/i);
  assert.match(S.bannerMessage([{ problem: 'unplaced' }], ['no_corridor']), /unplaced[\s\S]*corridor/i);
});

test('an unknown notice is ignored rather than shown as undefined', () => {
  assert.equal(S.bannerMessage([], ['something_new']), null);
});

test('a level change while the frame is up, or before any load, asks for the overview so the user frames that level', () => {
  assert.deepEqual(S.levelChangeRequest(true, true, 'Level 2', { xmin: 0 }), { type: 'overview', level: 'Level 2' });
  assert.deepEqual(S.levelChangeRequest(false, false, 'Level 2', null), { type: 'overview', level: 'Level 2' });
});

test('after a load, a level change re-reads 2D inside the same area and keeps the 3D', () => {
  const box = { xmin: 0, ymin: 0, xmax: 10, ymax: 10 };
  assert.deepEqual(S.levelChangeRequest(false, true, 'Level 2', box), { type: 'readModel', level: 'Level 2', crop: box, keep_meshes: true });
});

test('syncLabel names the 3D view in use', () => {
  assert.equal(S.syncLabel('{3D}'), '3D view: {3D}');
  assert.equal(S.syncLabel(null), 'Synced with Revit ✓');
  assert.equal(S.syncLabel(''), 'Synced with Revit ✓');
});
