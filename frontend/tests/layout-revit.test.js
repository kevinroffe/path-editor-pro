const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../js/layout-revit.js');

test('the right panel holds the three working step panels, in order, with plain titles', () => {
  assert.deepEqual(L.panelSections(), [
    { id: 'step-2', title: 'Tour & route' },
    { id: 'step-3', title: 'Camera style' },
    { id: 'step-4', title: 'Save' },
  ]);
});

test('the step chrome is hidden in the Revit window and shown in a browser tab', () => {
  assert.equal(L.shouldShowStepChrome('revit'), false);
  assert.equal(L.shouldShowStepChrome('browser'), true);
});

test('the load step, step dock, resize handle and the 3D panel are not shown in the Revit window', () => {
  assert.deepEqual(L.hiddenInRevit(), ['step-1', 'dock', 'resize-handle', 'preview-3d']);
});

test('panelSections returns a fresh list each time', () => {
  const a = L.panelSections();
  a.pop();
  assert.equal(L.panelSections().length, 3);
});

test('editing is allowed at step 2 and always in the Revit window; the video extras (intro, music, fades) only at step 4 of a tab', () => {
  assert.equal(L.editingOn(2, 'browser'), true);
  assert.equal(L.editingOn(3, 'browser'), false);
  assert.equal(L.editingOn(1, 'revit'), true);
  assert.equal(L.videoOn(4, 'browser'), true);
  assert.equal(L.videoOn(2, 'browser'), false);
  assert.equal(L.videoOn(4, 'revit'), false);   // no intro, outro, music or fades in the Revit window
  assert.equal(L.videoOn(2, 'revit'), false);
});
