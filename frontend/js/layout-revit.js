/* The Revit window is one screen instead of four steps: the plan, the 3D view, the video bar and one right-hand panel that
   holds the old step panels as sections. These are the pure decisions behind that; revit-shell.js does the DOM work. */

/* The step panels that become sections of the right panel, top to bottom. Step 1 (load) is replaced by the header controls. */
function panelSections() {
  return [
    { id: 'step-2', title: 'Tour & route' },
    { id: 'step-3', title: 'Camera style' },
    { id: 'step-4', title: 'Video & export' },
  ];
}

/* The wizard chrome (step dock, next/back, resize handle) only exists in a browser tab. */
function shouldShowStepChrome(mode) {
  return mode !== 'revit';
}

function hiddenInRevit() {
  return ['step-1', 'dock', 'resize-handle'];
}

/* Plan editing (clicking points, picking rooms) is a step-2 feature in a tab; in the Revit window it is always on. */
function editingOn(step, mode) {
  return mode === 'revit' || step === 2;
}

/* Playing the video with its music, title cards and fades is a step-4 feature in a tab; always on in the Revit window. */
function videoOn(step, mode) {
  return mode === 'revit' || step === 4;
}

if (typeof module === 'object') module.exports = { panelSections, shouldShowStepChrome, hiddenInRevit, editingOn, videoOn };
