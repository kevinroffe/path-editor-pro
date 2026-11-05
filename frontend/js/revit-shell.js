/* The Revit window: one screen (plan | 3D | panel, video bar below), the area frame, level choice, an orbit 3D view with the
   path drawn on it, a camera-view inset, extra timeline lanes, a live "you are here" marker on the plan, and point selection
   shared across views. Runs only under ?host=revit; in a browser tab this file does nothing. It builds on the page's own
   globals (state, p3, threeScene, drawRoute, ...) and on host.js, tracks.js, selection.js, path3d.js, crop.js,
   layout-revit.js and revit-session.js. */
(function () {
  'use strict';
  const Host = window.QbiqHost;
  if (!Host || Host.hostMode(window.location.search) !== 'revit') return;
  document.body.classList.add('host-revit');

  const EYE = 1.57;                                   // house-style eye height in metres
  const SVG = 'http://www.w3.org/2000/svg';
  const U = () => state.unitsToMetres || 1;
  const sel = createSelection();
  const el = id => document.getElementById(id);
  const toThree = w => new THREE.Vector3(w[0], w[2], -w[1]);   // world (x, y, z-up) -> three (x, up, -y)
  const inRevit = () => !!(window.chrome && window.chrome.webview);

  function wrap(name, after) {
    const original = window[name];
    window[name] = function (...args) {
      const result = original.apply(this, args);
      try { after.apply(this, args); } catch (e) { console.error(`revit-shell ${name}`, e); }
      return result;
    };
  }

  /* ── one screen: plan | 3D | right panel, with the video bar below (no steps) ── */
  (function layout() {
    const body = document.querySelector('.body');
    hiddenInRevit().forEach(id => { const node = el(id); if (node) node.classList.add('rv-hidden'); });
    const panel = document.createElement('div');
    panel.id = 'rv-panel';
    for (const section of panelSections()) {
      const node = el(section.id);
      if (!node) continue;
      const wrapper = document.createElement('section');
      wrapper.className = 'rv-sec';
      wrapper.innerHTML = `<button type="button" class="rv-sec-head"><span>${esc(section.title)}</span><i></i></button>`;
      wrapper.firstChild.onclick = () => wrapper.classList.toggle('closed');
      wrapper.appendChild(node);
      panel.appendChild(wrapper);
    }
    body.appendChild(panel);
    body.appendChild(el('video-timeline'));            // full-width bar under the plan and the 3D view
    // No intro, outro, music or logo in the Revit window: the bar is the walk itself.
    el('vtl-music').parentElement.classList.add('rv-hidden');
    const note = document.querySelector('.vtl-note');
    if (note) note.classList.add('rv-hidden');
    const saveHelp = document.querySelector('#step-4 > .sp-help');
    if (saveHelp) saveHelp.textContent = 'Save path (XML) in the header writes the camera path for Enscape. Save the path as JSON to continue it later.';
    state.step = 2;                                    // plan editing is always on (see editing() in the page)
    document.body.dataset.step = 2;
  })();

  /* ── header, banner, inspector, 3D toggles ── */
  const header = document.querySelector('.header');
  header.insertAdjacentHTML('beforeend',
    '<select id="rv-level" class="rv-select" title="Level of the plan"></select>' +
    '<button type="button" class="rv-btn" id="rv-area">Change area</button>' +
    '<span class="rv-chip" id="rv-sync">Synced with Revit ✓</span>' +
    '<button type="button" class="rv-btn" id="rv-json">Load JSON instead</button>' +
    '<button type="button" class="rv-btn" id="rv-refresh">Refresh model</button>' +
    '<button type="button" class="rv-btn primary" id="rv-save" disabled>Save path (XML)</button>');
  header.insertAdjacentHTML('afterend', '<div class="rv-banner" id="rv-banner" hidden></div>');
  el('p3d-fade').parentElement.insertAdjacentHTML('beforeend', '<div id="rv-inspector" hidden></div>');
  document.querySelector('.p3d-bar').insertAdjacentHTML('beforeend',
    '<label class="rv-tog"><input type="checkbox" id="rv-roofs"> Roofs</label><label class="rv-tog"><input type="checkbox" id="rv-ceilings"> Ceilings</label>');
  document.querySelector('.canvas-area').insertAdjacentHTML('afterbegin',
    '<div id="rv-crop-bar" hidden><span id="rv-crop-text">Drag the frame around the area to use. Anything outside it is ignored.</span>' +
    '<button type="button" class="rv-btn primary" id="rv-crop-ok">Use this area</button>' +
    '<button type="button" class="rv-btn" id="rv-crop-all">Use everything</button>' +
    '<button type="button" class="rv-btn" id="rv-crop-cancel" hidden>Cancel</button></div>');

  el('rv-json').onclick = () => el('file-folder-input').click();
  el('rv-save').onclick = () => exportRoute('xml');
  el('rv-refresh').onclick = () => (inRevit() ? Host.postToHost({ type: 'refreshModel' }) : loadCurrent(true));

  function showIssues(issues, notices) {
    const banner = el('rv-banner'), message = bannerMessage(issues, notices);
    if (!message) { banner.hidden = true; return; }
    banner.innerHTML = `<span>${esc(message)}</span><button type="button" class="rv-btn" id="rv-json2">Load JSON instead</button>`;
    banner.hidden = false;
    el('rv-json2').onclick = () => el('file-folder-input').click();
  }

  /* ── loading the model ── */
  let loadedOnce = false;                // after the first full load, later reads keep the user's points
  let lastBox = null;                    // the area in model feet that was last read; null = everything

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
    if (bad) toast(`${bad} point${bad > 1 ? 's are' : ' is'} outside the walkable floor or area (marked amber)`, 'inf', 6000);
  }

  function fillLevels(data) {
    const select = el('rv-level');
    const levels = data.levels && data.levels.length ? data.levels : [data.level];
    select.innerHTML = levels.map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
    select.value = data.level;
  }

  const currentLevel = () => el('rv-level').value || state.level;

  async function fetchCurrent() {
    const r = await fetch(`${API}/api/revit/current`);
    if (!r.ok) throw new Error('No Revit model has been loaded yet');
    return r.json();
  }

  async function loadCurrent(keepSession) {
    let data;
    try { data = await fetchCurrent(); } catch (e) { toast(e.message, 'err'); return; }
    const snap = keepSession ? captureSession(state) : null;     // applyFloorPlan resets the route, tour picks, entrance and step
    applyFloorPlan(data);
    fitted = false;
    if (snap) {
      const step = restoreSession(state, snap);
      if (step !== state.step) goStep(step);
      if (state.waypoints.length) {
        await flagInvalid();
        renderRoute(); updateWpList();
      }
    }
    endCrop();
    fillLevels(data);
    el('rv-sync').textContent = syncLabel(data.view_name);
    loadedOnce = true;
    showIssues(data.room_issues, data.level_notices);
    ensure3D();
  }

  async function showOverview() {
    let data;
    try { data = await fetchCurrent(); } catch (e) { toast(e.message, 'err'); return; }
    const snap = loadedOnce ? captureSession(state) : null;
    applyFloorPlan(data);
    if (snap) { restoreSession(state, snap); renderRoute(); updateWpList(); }
    fillLevels(data);
    ensure3D();
    startCrop(data);
  }

  Host.handlers.modelReading = () => showLoading('Reading the Revit model…');
  Host.handlers.modelOverview = () => showOverview().finally(hideLoading);
  Host.handlers.modelLoaded = () => loadCurrent(loadedOnce).finally(hideLoading);
  Host.handlers.modelRefreshed = () => loadCurrent(true).finally(hideLoading);
  Host.handlers.modelFailed = () => hideLoading();

  /* Ask the add-in; outside Revit (the demo page) there is nobody to ask, so the frame just closes. */
  function sendRead(message) {
    if (inRevit()) { Host.postToHost(message); return; }
    endCrop();
    toast('Demo page: no Revit to read from', 'inf');
  }

  el('rv-level').onchange = () => sendRead(levelChangeRequest(!!window.QbiqCropping, loadedOnce, currentLevel(), lastBox));
  el('rv-area').onclick = () => (inRevit() ? Host.postToHost({ type: 'overview', level: currentLevel() })
    : startCrop({ crop_default: lastBox }));

  /* ── the area frame ── */
  let cropRect = null, cropBounds = null, drag = null;

  function planPoint(e) {
    const pt = svgEl.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(gRoot.getScreenCTM().inverse());
  }

  function cropLayer() {
    if (!gRoot) return null;
    let g = el('rv-crop');
    if (!g || !g.isConnected) {
      g = document.createElementNS(SVG, 'g');
      g.id = 'rv-crop';
      gRoot.appendChild(g);
    }
    return g;
  }

  function drawCrop() {
    const g = cropLayer();
    if (!g || !cropRect || !cropBounds) return;
    const r = cropRect, b = cropBounds, k = circleR();
    const pad = Math.max(b.x1 - b.x0, b.y1 - b.y0);
    const handles = [[r.x0, r.y0], [r.x1, r.y0], [r.x0, r.y1], [r.x1, r.y1], [(r.x0 + r.x1) / 2, r.y0], [(r.x0 + r.x1) / 2, r.y1], [r.x0, (r.y0 + r.y1) / 2], [r.x1, (r.y0 + r.y1) / 2]];
    g.innerHTML =
      `<path d="M${b.x0 - pad} ${b.y0 - pad}H${b.x1 + pad}V${b.y1 + pad}H${b.x0 - pad}Z M${r.x0} ${r.y0}V${r.y1}H${r.x1}V${r.y0}Z" ` +
      'fill="rgba(30,36,48,.45)" fill-rule="evenodd" pointer-events="none"/>' +
      `<rect x="${r.x0}" y="${r.y0}" width="${r.x1 - r.x0}" height="${r.y1 - r.y0}" fill="none" stroke="#2f6bff" stroke-width="${k * 0.25}" stroke-dasharray="${k} ${k * 0.6}" pointer-events="none"/>` +
      handles.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="${k * 0.9}" fill="#fff" stroke="#2f6bff" stroke-width="${k * 0.25}" pointer-events="none"/>`).join('');
  }

  function onCropDown(e) {
    if (!window.QbiqCropping || e.button !== 0 || !svgEl) return;
    const p = planPoint(e);
    const handle = hitTest(cropRect, p, circleR() * 1.6);
    drag = handle ? { handle, start: p, rect: { ...cropRect } } : { handle: 'new', start: p, before: { ...cropRect } };
    try { svgEl.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic or already-released pointer: dragging still works */ }
    e.stopPropagation(); e.preventDefault();
  }

  function onCropMove(e) {
    if (!drag) return;
    const p = planPoint(e);
    cropRect = drag.handle === 'new'
      ? clampRect(normaliseRect(drag.start, p), cropBounds)
      : applyDrag(drag.rect, drag.handle, p.x - drag.start.x, p.y - drag.start.y, cropBounds);
    drawCrop();
  }

  function onCropUp() {
    if (drag && drag.handle === 'new') { cropRect = keepIfUsable(cropRect, drag.before); drawCrop(); }   // a click must not lose the frame
    drag = null;
  }

  function startCrop(data) {
    if (!svgEl || !state.bounds) return;
    window.QbiqCropping = true;
    document.body.classList.add('rv-cropping');
    cropBounds = fromModelBox(state.bounds);
    const start = data && data.crop_default ? fromModelBox(data.crop_default) : lastBox ? fromModelBox(lastBox) : cropBounds;
    const clamped = clampRect(start, cropBounds);
    cropRect = isUsable(clamped) ? clamped : { ...cropBounds };
    el('rv-crop-bar').hidden = false;
    el('rv-crop-cancel').hidden = !loadedOnce;
    svgEl.addEventListener('pointerdown', onCropDown, true);
    svgEl.addEventListener('pointermove', onCropMove);
    svgEl.addEventListener('pointerup', onCropUp);
    drawCrop();
  }

  function endCrop() {
    window.QbiqCropping = false;
    document.body.classList.remove('rv-cropping');
    el('rv-crop-bar').hidden = true;
    const g = el('rv-crop');
    if (g) g.remove();
    if (svgEl) {
      svgEl.removeEventListener('pointerdown', onCropDown, true);
      svgEl.removeEventListener('pointermove', onCropMove);
      svgEl.removeEventListener('pointerup', onCropUp);
    }
    drag = null;
  }

  el('rv-crop-ok').onclick = () => {
    if (!isUsable(cropRect)) { toast('Drag a bigger frame around the area first', 'inf'); return; }
    lastBox = toModelBox(cropRect);
    sendRead({ type: 'readModel', level: currentLevel(), crop: lastBox });
  };
  el('rv-crop-all').onclick = () => {
    lastBox = null;
    sendRead({ type: 'readModel', level: currentLevel() });
  };
  el('rv-crop-cancel').onclick = () => sendRead({ type: 'readModel', level: currentLevel(), crop: lastBox });   // back to the area it had

  if (new URLSearchParams(window.location.search).get('demo') === '1') {
    loadDemo().then(() => { ensure3D(); });            // development without Revit: the demo plan stands in for a model
  }
  if (new URLSearchParams(window.location.search).get('demo') === 'crop') {
    loadDemo().then(() => { ensure3D(); startCrop({}); });
  }

  /* ── "you are here": a dot and view cone on the plan that follow the play head ── */
  function hereLayer() {
    if (!gRoot) return null;
    let g = el('rv-here');
    if (!g || !g.isConnected) {
      g = document.createElementNS(SVG, 'g');
      g.id = 'rv-here';
      g.setAttribute('pointer-events', 'none');
      gRoot.appendChild(g);
    }
    return g;
  }

  function drawHere(t) {
    const g = hereLayer();
    if (!g) return;
    if (!p3.frames || p3.frames.length < 2 || !state.bounds) { g.innerHTML = ''; return; }
    const n = p3.frames.length, raw = Math.min(1, Math.max(0, t)) * (n - 1);
    const i = Math.min(Math.floor(raw), n - 2), k = raw - i, a = p3.frames[i], b = p3.frames[i + 1];
    const x = a.x + (b.x - a.x) * k, y = a.y + (b.y - a.y) * k, yaw = lerpYaw(a.yaw, b.yaw, k) * Math.PI / 180;
    const r = circleR() * 1.3, len = r * 6, half = (cam.fov / 2) * Math.PI / 180;
    const tip = s => `${(x + len * Math.cos(yaw + s)).toFixed(3)},${(y + len * Math.sin(yaw + s)).toFixed(3)}`;
    g.innerHTML =
      `<polygon points="${x},${y} ${tip(-half)} ${tip(half)}" fill="#d64545" fill-opacity=".22" stroke="#d64545" stroke-opacity=".6" stroke-width="${r * 0.12}"/>` +
      `<circle cx="${x}" cy="${y}" r="${r}" fill="#d64545" stroke="#fff" stroke-width="${r * 0.3}"/>`;
  }
  wrap('updateCameraFromT', drawHere);

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
    const base = levelElevationM();                    // look at the loaded level, not at storey 0
    overview.position.set(f.cx, base + r * 1.5, f.cz + r * 1.3);
    controls.target.set(f.cx, base, f.cz);
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
    const pts = routeToWorld(line, U(), EYE, levelElevationM()).map(toThree);
    if (pts.length > 1) {
      const curve = new THREE.CatmullRomCurve3(pts.filter((p, i) => i === 0 || p.distanceTo(pts[i - 1]) > 1e-6), false, 'centripetal');
      group.add(new THREE.Mesh(new THREE.TubeGeometry(curve, Math.min(600, pts.length * 2), 0.07, 5, false),
        new THREE.MeshBasicMaterial({ color: 0x2f6bff })));
    }
    const world = routeToWorld(wps.map(w => [w.x, w.y]), U(), EYE, levelElevationM());
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

  /* Meshes of a type the user switched off (roofs and ceilings hide the inside from above). Returns what to restore. */
  function hideSwitchedOff(scene) {
    const off = new Set();
    if (!el('rv-roofs').checked) off.add('roof');
    if (!el('rv-ceilings').checked) off.add('ceiling');
    const restore = [];
    scene.traverse(o => {
      if (o.isMesh && off.has(o.userData.meshType) && o.visible) { restore.push(o); o.visible = false; }
    });
    return restore;
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
      const hidden = hideSwitchedOff(scene);
      renderer.render(scene, overview);
      hidden.forEach(o => { o.visible = true; });
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
      const r = ray(e), hit = floorHit([r.origin.x, -r.origin.z, r.origin.y], [r.direction.x, -r.direction.z, r.direction.y], EYE + levelElevationM());
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
      (w.invalid ? '<div class="rv-warn">Outside the walkable floor or area</div>' : '') +
      `<div class="rv-fld">Eye height<input value="${EYE.toFixed(2)} m" readonly></div>` +
      `<div class="rv-fld">Look-at offset<input id="rv-yaw" type="number" step="5" value="${w.yawOffset || 0}"></div>` +
      (dwell != null ? `<div class="rv-fld">Pause (s)<input id="rv-dwell" type="number" step="0.5" min="0.5" max="10" value="${dwell}"></div>` : '');
    box.hidden = false;
    const apply = () => { markHandEdited(); debounceSpline(); schedulePreview(); };
    el('rv-yaw').onchange = ev => { w.yawOffset = Number(ev.target.value) || 0; apply(); };
    if (dwell != null) el('rv-dwell').onchange = ev => { setWpDwell(i, ev.target.value); apply(); };
  }

  /* ── timeline lanes: camera, look-at, pauses (the video lane is the page's own) ── */
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
    const tracks = buildTracks({ plan: await r.json(), frames: p3.frames, plain: true });
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
