/* The Revit window: header controls, model loading from the add-in, an orbit 3D view with the path drawn on it,
   a camera-view inset, extra timeline lanes and point selection shared across views.
   Runs only under ?host=revit; in a browser tab this file does nothing. It builds on the page's own globals
   (state, p3, threeScene, drawRoute, ...) and on host.js, tracks.js, selection.js and path3d.js. */
(function () {
  'use strict';
  const Host = window.QbiqHost;
  if (!Host || Host.hostMode(window.location.search) !== 'revit') return;
  document.body.classList.add('host-revit');

  const EYE = 1.57;                                   // house-style eye height in metres
  const U = () => state.unitsToMetres || 1;
  const sel = createSelection();
  const el = id => document.getElementById(id);
  const toThree = w => new THREE.Vector3(w[0], w[2], -w[1]);   // world (x, y, z-up) -> three (x, up, -y)

  function wrap(name, after) {
    const original = window[name];
    window[name] = function (...args) {
      const result = original.apply(this, args);
      try { after.apply(this, args); } catch (e) { console.error(`revit-shell ${name}`, e); }
      return result;
    };
  }

  /* ── header, banner, inspector ── */
  const header = document.querySelector('.header');
  header.insertAdjacentHTML('beforeend',
    '<span class="rv-chip" id="rv-sync">Synced with Revit ✓</span>' +
    '<button type="button" class="rv-btn" id="rv-json">Load JSON instead</button>' +
    '<button type="button" class="rv-btn" id="rv-refresh">Refresh model</button>' +
    '<button type="button" class="rv-btn primary" id="rv-save" disabled>Save path (XML)</button>');
  header.insertAdjacentHTML('afterend', '<div class="rv-banner" id="rv-banner" hidden></div>');
  el('p3d-fade').parentElement.insertAdjacentHTML('beforeend', '<div id="rv-inspector" hidden></div>');

  el('rv-json').onclick = () => el('file-folder-input').click();
  el('rv-save').onclick = () => exportRoute('xml');
  el('rv-refresh').onclick = () => {
    if (window.chrome && window.chrome.webview) Host.postToHost({ type: 'refreshModel' });
    else loadCurrent(true);
  };

  function showIssues(issues) {
    const banner = el('rv-banner');
    if (!issues || !issues.length) { banner.hidden = true; return; }
    const counts = issues.reduce((m, i) => ((m[i.problem] = (m[i.problem] || 0) + 1), m), {});
    const parts = Object.entries(counts).map(([k, n]) => `${n} ${k.replace('_', ' ')}`).join(', ');
    banner.innerHTML = `<span><b>${issues.length} Revit room${issues.length > 1 ? 's' : ''} look broken</b> (${esc(parts)}). ` +
      'Auto-path still works, but tours may miss them.</span><button type="button" class="rv-btn" id="rv-json2">Load JSON instead</button>';
    banner.hidden = false;
    el('rv-json2').onclick = () => el('file-folder-input').click();
  }

  /* ── loading the model ── */
  function ensure3D() {
    if (!el('preview-3d').classList.contains('visible')) toggle3DPanel();
  }

  async function flagInvalid() {
    const pts = state.waypoints.map(w => [w.x, w.y]);
    if (!pts.length) return;
    const r = await fetch(`${API}/api/points-valid`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ points: pts }) });
    if (!r.ok) return;
    const { valid } = await r.json();
    state.waypoints.forEach((w, i) => { w.invalid = !valid[i]; });
    const bad = valid.filter(v => !v).length;
    if (bad) toast(`${bad} point${bad > 1 ? 's are' : ' is'} no longer on walkable floor (marked amber)`, 'inf', 6000);
  }

  async function loadCurrent(refresh) {
    const r = await fetch(`${API}/api/revit/current`);
    if (!r.ok) { toast('No Revit model has been loaded yet', 'err'); return; }
    const data = await r.json();
    const kept = refresh ? state.waypoints : [];
    applyFloorPlan(data);
    fitted = false;
    if (kept.length) {
      state.waypoints = kept;
      await flagInvalid();
      renderRoute(); updateWpList();
    }
    showIssues(data.room_issues);
    ensure3D();
  }

  Host.handlers.modelLoaded = () => loadCurrent(false);
  Host.handlers.modelRefreshed = () => loadCurrent(true);

  if (new URLSearchParams(window.location.search).get('demo') === '1') {
    loadDemo().then(() => { ensure3D(); });            // development without Revit: the demo plan stands in for a model
  }

  /* ── 3D: overview camera, path overlay, camera inset ── */
  let overview = null, controls = null, group = null, markers = [], fitted = false, overlayDirty = true, lastBounds = null;

  function ensureOverview(renderer) {
    if (overview) return;
    overview = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
    controls = new THREE_ADDONS.OrbitControls(overview, renderer.domElement);
    controls.enableDamping = false;
    fitted = false;
  }

  function fit() {
    const f = planFrame();
    const r = Math.max(f.hw, f.hd);
    overview.position.set(f.cx, r * 1.5, f.cz + r * 1.3);
    controls.target.set(f.cx, 0, f.cz);
    controls.update();
    fitted = true;
  }

  function frameAt(x, y) {
    let best = null, bestD = Infinity;
    for (const f of p3.frames) { const d = (f.x - x) ** 2 + (f.y - y) ** 2; if (d < bestD) { bestD = d; best = f; } }
    return best;
  }

  function disposeGroup() {
    if (!group) return;
    group.traverse(o => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); });
    group.parent && group.parent.remove(group);
    group = null; markers = [];
  }

  function rebuildOverlay(scene) {
    disposeGroup();
    overlayDirty = false;
    const wps = state.waypoints;
    if (!wps.length) return;
    group = new THREE.Group();
    const segs = (state.splineSegments || []).filter(s => s.length > 1);
    const line = (segs.length ? segs.flat() : wps.map(w => [w.x, w.y]));
    const pts = routeToWorld(line, U(), EYE).map(toThree);
    if (pts.length > 1) {
      const curve = new THREE.CatmullRomCurve3(pts.filter((p, i) => i === 0 || p.distanceTo(pts[i - 1]) > 1e-6), false, 'centripetal');
      group.add(new THREE.Mesh(new THREE.TubeGeometry(curve, Math.min(600, pts.length * 2), 0.07, 5, false),
        new THREE.MeshBasicMaterial({ color: 0x2f6bff })));
    }
    const world = routeToWorld(wps.map(w => [w.x, w.y]), U(), EYE);
    const selected = state.selectedWp;
    world.forEach((wp, i) => {
      const colour = i === selected ? 0xd99000 : wps[i].invalid ? 0xf0b429 : i === 0 ? 0x31a354 : i === wps.length - 1 ? 0xd64545 : 0x2f6bff;
      const ball = new THREE.Mesh(new THREE.SphereGeometry(i === selected ? 0.3 : 0.22, 16, 12),
        new THREE.MeshBasicMaterial({ color: colour, depthTest: false }));
      ball.renderOrder = 10;
      ball.position.copy(toThree(wp));
      ball.userData.wp = i;
      group.add(ball); markers.push(ball);
      const f = frameAt(wps[i].x, wps[i].y);
      if (f) {
        const { apex, baseCorners } = coneParams(wp, f.yaw, cam.fov, 2.4);
        const v = [apex, ...baseCorners].map(toThree);
        const geo = new THREE.BufferGeometry().setFromPoints(
          [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1]].flatMap(t => t.map(k => v[k])));
        group.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: colour, transparent: true, opacity: 0.2, side: THREE.DoubleSide, depthWrite: false })));
      }
    });
    scene.add(group);
  }

  window.QbiqRevit = {
    /* The overview camera and point markers, for tests that drive the 3D view with synthetic pointer events. */
    debug: () => ({ overview, markers, controls }),
    /* Replaces the page's single render call: orbit overview, then the first-person camera as an inset. */
    render(renderer, scene, fpCam) {
      ensureOverview(renderer);
      if (lastBounds !== state.bounds) { lastBounds = state.bounds; fitted = false; }
      if (!fitted && state.bounds) fit();
      if (overlayDirty || (group && group.parent !== scene)) rebuildOverlay(scene);
      const size = renderer.getSize(new THREE.Vector2());
      overview.aspect = size.x / size.y; overview.updateProjectionMatrix();
      renderer.setScissorTest(false);
      renderer.setViewport(0, 0, size.x, size.y);
      renderer.render(scene, overview);
      if (!p3.frames.length) return;
      const iw = Math.round(size.x * 0.28), ih = Math.round(iw * 9 / 16), x = size.x - iw - 12, y = 12;
      const savedAspect = fpCam.aspect;
      fpCam.aspect = iw / ih; fpCam.updateProjectionMatrix();
      if (group) group.visible = false;
      renderer.setScissorTest(true);
      renderer.setViewport(x, y, iw, ih); renderer.setScissor(x, y, iw, ih);
      renderer.render(scene, fpCam);
      renderer.setScissorTest(false);
      if (group) group.visible = true;
      fpCam.aspect = savedAspect; fpCam.updateProjectionMatrix();
    },
  };

  /* ── picking and dragging points in the 3D view ── */
  let raycaster = null, dragging = null;          // THREE is only available once the module build has booted
  function ray(e) {
    raycaster = raycaster || new THREE.Raycaster();
    const canvas = e.currentTarget, r = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), overview);
    return raycaster.ray;
  }
  function pick(e) {
    if (!overview || !markers.length) return null;
    const hit = ray(e) && raycaster.intersectObjects(markers, false)[0];
    return hit ? hit.object.userData.wp : null;
  }
  function onCanvasReady() {
    const canvas = el('preview-canvas');
    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      const i = pick(e);
      if (i == null) return;
      controls.enabled = false; dragging = i;
      sel.select(`wp:${i}`);
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
    }, true);
    canvas.addEventListener('pointermove', e => {
      if (dragging == null) return;
      const r = ray(e), hit = floorHit([r.origin.x, -r.origin.z, r.origin.y], [r.direction.x, -r.direction.z, r.direction.y], EYE);
      if (!hit) return;
      const w = state.waypoints[dragging];
      w.x = hit[0] / U(); w.y = -hit[1] / U();
      overlayDirty = true;
    });
    const end = e => {
      if (dragging == null) return;
      dragging = null; controls.enabled = true;
      markHandEdited(); renderRoute(); updateWpList();
    };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
  }
  onCanvasReady();

  /* ── selection shared with the page's own plan selection ── */
  sel.subscribe(id => {
    const i = id && id.startsWith('wp:') ? Number(id.slice(3)) : null;
    if (state.selectedWp !== i) { state.selectedWp = i; renderRoute(); }
    overlayDirty = true;
    renderInspector();
    markLanes();
  });
  const pageToSelection = () => sel.select(state.selectedWp == null ? null : `wp:${state.selectedWp}`);

  function renderInspector() {
    const box = el('rv-inspector'), i = state.selectedWp, w = i == null ? null : state.waypoints[i];
    if (!w) { box.hidden = true; return; }
    const dwell = w.stop ? w.stop.dwell_s : null;
    box.innerHTML = `<h4><span>Point ${i + 1}</span><span style="color:var(--text3)">${esc(w.stop?.label || '')}</span></h4>` +
      (w.invalid ? '<div class="rv-warn">No longer on walkable floor after the refresh</div>' : '') +
      `<div class="rv-fld">Eye height<input value="${EYE.toFixed(2)} m" readonly></div>` +
      `<div class="rv-fld">Look-at offset<input id="rv-yaw" type="number" step="5" value="${w.yawOffset || 0}"></div>` +
      (dwell != null ? `<div class="rv-fld">Pause (s)<input id="rv-dwell" type="number" step="0.5" min="0.5" max="10" value="${dwell}"></div>` : '');
    box.hidden = false;
    const apply = () => { markHandEdited(); debounceSpline(); schedulePreview(); };
    el('rv-yaw').onchange = ev => { w.yawOffset = Number(ev.target.value) || 0; apply(); };
    if (dwell != null) el('rv-dwell').onchange = ev => { setWpDwell(i, ev.target.value); apply(); };
  }

  /* ── timeline lanes: camera, look-at, pauses (video and music are the page's own) ── */
  let laneSeq = 0, laneHost = null;
  function ensureLaneHost() {
    if (laneHost) return laneHost;
    laneHost = document.createElement('div');
    laneHost.id = 'rv-lanes';
    el('vtl-video').parentElement.after(laneHost);
    return laneHost;
  }
  const pct = (s, total) => `${(s / total * 100).toFixed(3)}%`;

  function laneHtml(name, lane, total) {
    const clips = lane.clips.map(c => {
      if (lane.id === 'camera') return `<i class="rv-key" data-sec="${c.startS}" style="left:${pct(c.startS, total)}"></i>`;
      return `<span class="rv-clip ${c.kind}" style="left:${pct(c.startS, total)};width:${pct(c.endS - c.startS, total)}"></span>`;
    }).join('');
    return `<div class="vtl-lane"><span class="vtl-name">${name}</span><div class="vtl-track rv-track" data-lane="${lane.id}">${clips}</div></div>`;
  }

  function waypointMarkers(total) {
    const tl = p3.timeline;
    return state.waypoints.map((w, i) => {
      const m = projectToRoute(p3.frames, p3.dists, U(), w.x, w.y);
      const sec = timelineSecondAt(tl, walkTimeAtDistance(p3.dists, p3.duration, m));
      return `<i class="rv-wp${w.invalid ? ' bad' : ''}" data-wp="${i}" data-sec="${sec}" style="left:${pct(sec, total)}"></i>`;
    }).join('');
  }

  async function renderLanes() {
    if (!p3.frames.length || state.waypoints.length < 2 || !p3.timeline) return;
    const seq = ++laneSeq;
    const settings = { level: state.level, duration: cam.dur, start_pan: cam.startPan, smoothing: cam.smo, fov: cam.fov, fps: 30,
      uturn_radius: cam.utr, units_to_metres: state.unitsToMetres };
    const r = await fetch(`${API}/api/camera-plan`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ waypoints: state.waypoints.map(wpWire), cuts: cutIndices(), settings }) });
    if (!r.ok || seq !== laneSeq) return;
    const tracks = buildTracks({ plan: await r.json(), frames: p3.frames, fades: state.video.fades || [], music: null });
    const [, camera, lookat, pauses] = tracks.lanes;
    const total = p3.timeline.total;
    ensureLaneHost().innerHTML = laneHtml('Camera', camera, total) + laneHtml('Look-at', lookat, total) + laneHtml('Pauses', pauses, total);
    laneHost.querySelector('[data-lane="camera"]').insertAdjacentHTML('beforeend', waypointMarkers(total));
    laneHost.querySelectorAll('.rv-track').forEach(track => {
      track.onpointerdown = ev => {
        const wp = ev.target.dataset && ev.target.dataset.wp;
        if (wp != null) sel.select(`wp:${wp}`);
        const r2 = track.getBoundingClientRect();
        seekTimeline(((ev.clientX - r2.left) / r2.width) * total);
      };
    });
    markLanes();
  }

  function markLanes() {
    if (!laneHost) return;
    laneHost.querySelectorAll('.rv-wp').forEach(n => n.classList.toggle('sel', Number(n.dataset.wp) === state.selectedWp));
  }

  /* ── keep the preview in step with the route ── */
  let previewTimer = null;
  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      if (state.loaded && state.waypoints.length >= 2 && previewSig() !== p3.framesSig) loadPreviewFrames();
    }, 700);
  }

  wrap('drawRoute', () => {
    overlayDirty = true;
    el('rv-save').disabled = state.waypoints.length < 2;
    pageToSelection();
    schedulePreview();
  });
  wrap('renderTimelineLanes', renderLanes);
  wrap('updateWpList', () => {
    document.querySelectorAll('#wp-list .wp-row').forEach((row, i) => row.classList.toggle('rv-invalid', !!(state.waypoints[i] && state.waypoints[i].invalid)));
  });
})();
