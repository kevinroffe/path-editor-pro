/* One selected path point shared by the 3D view, plan, point list and timeline. Ids are "kf:<index>". */

function createSelection() {
  let current = null;
  const listeners = new Set();
  return {
    select(id) {
      if (id === current) return;
      current = id;
      for (const fn of [...listeners]) fn(current);
    },
    get: () => current,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

if (typeof module === 'object') module.exports = { createSelection };
