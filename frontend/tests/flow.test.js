const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const F = require('../js/flow.js');

const cases = [
  [1, { loaded: false, waypointCount: 0 }, true],
  [2, { loaded: false, waypointCount: 0 }, false],
  [2, { loaded: true, waypointCount: 0 }, true],
  [3, { loaded: true, waypointCount: 1 }, false],
  [3, { loaded: true, waypointCount: 2 }, true],
  [4, { loaded: false, waypointCount: 5 }, false],
];
for (const [step, s, ok] of cases) {
  test(`step ${step} with ${JSON.stringify(s)} is ${ok ? 'open' : 'closed'}`, () => assert.equal(F.canEnterStep(step, s), ok));
}

test('steps are named for the dock', () =>
  assert.deepEqual(F.STEPS, ['Load plan', 'Rooms & route', 'Camera style', 'Preview & export']));

test('test_index_has_no_root_absolute_assets', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  assert.equal(html.match(/(src|href)="\/(?!\/)[^"]*"/g), null);
});
