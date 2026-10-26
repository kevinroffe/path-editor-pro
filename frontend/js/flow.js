/* The four guided steps and when each one can be opened. */

const STEPS = ['Load plan', 'Rooms & route', 'Camera style', 'Preview & export'];

/* Step 1 is always open; step 2 needs a plan; steps 3 and 4 also need a finished route of two or more waypoints. */
function canEnterStep(step, s) {
  if (step === 1) return true;
  if (step === 2) return !!s.loaded;
  return !!s.loaded && s.waypointCount >= 2 && !s.busy;
}

if (typeof module === 'object') module.exports = { STEPS, canEnterStep };
