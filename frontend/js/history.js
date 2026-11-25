/* Undo / redo for the route: a list of saved states (as strings) with the current one in between. Pure, so it is tested in node;
   revit-shell.js decides what a state holds and when one is recorded. */

function createHistory(limit = 100) {
  let past = [], future = [], current = null;
  return {
    /* Start over at this state (a newly loaded model). */
    reset(state) { past = []; future = []; current = state; },
    /* A change: the current state moves to the past; false when nothing changed. */
    record(state) {
      if (state === current) return false;
      if (current !== null) past.push(current);
      if (past.length > limit) past.shift();
      current = state;
      future = [];
      return true;
    },
    /* The state to go back to, or null when there is none. */
    undo() {
      if (!past.length) return null;
      future.push(current);
      current = past.pop();
      return current;
    },
    redo() {
      if (!future.length) return null;
      past.push(current);
      current = future.pop();
      return current;
    },
    canUndo: () => past.length > 0,
    canRedo: () => future.length > 0,
  };
}

if (typeof module === 'object') module.exports = { createHistory };
