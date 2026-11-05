/* The Revit window: one screen (plan | panel, video bar below). The plan has two modes, Plan (the colored rooms) and Top view
   (the 3D model from straight above), and carries everything the path means: points, a view cone at each point, pauses, and a
   live "you are here" dot that follows the play head. Also: the area frame, level choice, timeline lanes, point selection.
   Runs only under ?host=revit; in a browser tab this file does nothing. It builds on the page's own globals (state, p3,
   svgEl, gRoot, drawRoute, ...) and on host.js, tracks.js, selection.js, crop.js, plan-view.js, topview.js, layout-revit.js
   and revit-session.js. */
(function () {
  'use strict';
  const Host = window.QbiqHost;
  if (!Host || Host.hostMode(window.location.search) !== 'revit') return;
  document.body.classList.add('host-revit');

  const SVG = 'http://www.w3.org/2000/svg';
  const sel = createSelection();
  const el = id => document.getElementById(id);
  const inRevit = () => !!(window.chrome && window.chrome.webview);
  let previewOn = true;                  // the 3D preview pane beside the plan (header toggle); off = faster 2D-only reads

  function wrap(name, after) {
    const original = window[name];
    window[name] = function (...args) {
      const result = original.apply(this, args);
      try { after.apply(this, args); } catch (e) { console.error(`revit-shell ${name}`, e); }
      return result;
    };
  }

  /* The page's render loop advances the video clock and updates the camera; it only draws while the preview pane is open. */
  window.QbiqRevit = { render(renderer, scene, camera) { if (previewOn) renderer.render(scene, camera); } };

  /* ── one screen: plan | right panel, with the video bar below (no steps, no 3D window) ── */
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
    body.appendChild(el('video-timeline'));            // full-width bar under the plan
    // No intro, outro, music or logo in the Revit window: the bar is the walk itself.
    el('vtl-music').parentElement.classList.add('rv-hidden');
    const note = document.querySelector('.vtl-note');
    if (note) note.classList.add('rv-hidden');
    const saveHelp = document.querySelector('#step-4 > .sp-help');
    if (saveHelp) saveHelp.textContent = 'Save path (XML) in the header writes the camera path for Enscape. Save the path as JSON to continue it later.';
    state.step = 2;                                    // plan editing is always on (see editing() in the page)
    document.body.dataset.step = 2;
  })();

  /* ── header, banner, inspector, mode switch, area bar ── */
  const header = document.querySelector('.header');
  header.insertAdjacentHTML('beforeend',
    '<select id="rv-level" class="rv-select" title="Level of the plan"></select>' +
    '<button type="button" class="rv-btn" id="rv-area">Change area</button>' +
    '<span class="rv-chip" id="rv-sync">Synced with Revit ✓</span>' +
    '<button type="button" class="rv-btn primary" id="rv-prev" aria-pressed="true" title="Show or hide the 3D preview next to the plan">3D preview</button>' +
    '<button type="button" class="rv-btn" id="rv-json">Load JSON instead</button>' +
    '<button type="button" class="rv-btn" id="rv-cam" aria-pressed="false" hidden title="Experimental: moves the active Revit 3D view along the path while you play">Revit camera</button>' +
    '<span class="rv-chip" id="rv-cam-note" hidden></span>' +
    '<button type="button" class="rv-btn" id="rv-refresh">Refresh model</button>' +
    '<button type="button" class="rv-btn primary" id="rv-save" disabled>Save path (XML)</button>');
  header.insertAdjacentHTML('afterend', '<div class="rv-banner" id="rv-banner" hidden></div>');
  const canvasArea = document.querySelector('.canvas-area');
  canvasArea.insertAdjacentHTML('afterbegin',
    '<div id="rv-crop-bar" hidden><span id="rv-crop-text">Drag the frame around the area to use. Anything outside it is ignored.</span>' +
    '<button type="button" class="rv-btn primary" id="rv-crop-ok">Use this area</button>' +
    '<button type="button" class="rv-btn" id="rv-crop-all">Use everything</button>' +
    '<button type="button" class="rv-btn" id="rv-crop-cancel" hidden>Cancel</button></div>' +
    '<div id="rv-modes" role="group" aria-label="Plan mode"><button type="button" class="on" data-mode="plan">Plan</button>' +
    '<button type="button" data-mode="top">Top view</button></div>' +
    '<div id="rv-inspector" hidden></div>');

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

  /* Starts the page's render loop (it advances the video clock) without showing any 3D. */
  function ensureLoop() {
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
    ensureLoop();
    if (pendingTop && haveMeshes()) { pendingTop = false; mode = 'top'; }
    applyMode();
  }

  async function showOverview() {
    let data;
    try { data = await fetchCurrent(); } catch (e) { toast(e.message, 'err'); return; }
    const snap = loadedOnce ? captureSession(state) : null;
    applyFloorPlan(data);
    if (snap) { restoreSession(state, snap); renderRoute(); updateWpList(); }
    fillLevels(data);
    ensureLoop();
    mode = 'plan';
    applyMode();
    startCrop(data);
  }

  Host.handlers.modelReading = () => showLoading('Reading the Revit model…');
  Host.handlers.modelOverview = () => showOverview().finally(hideLoading);
  Host.handlers.modelLoaded = () => loadCurrent(loadedOnce).finally(hideLoading);
  Host.handlers.modelRefreshed = () => loadCurrent(true).finally(hideLoading);
  Host.handlers.modelFailed = () => { pendingTop = false; hideLoading(); };

  /* Ask the add-in; outside Revit (the demo page) there is nobody to ask, so the frame just closes. */
  function sendRead(message) {
    if (inRevit()) { Host.postToHost(message); return; }
    endCrop();
    toast('Demo page: no Revit to read from', 'inf');
  }

  el('rv-level').onchange = () => sendRead(levelChangeRequest(!!window.QbiqCropping, loadedOnce, currentLevel(), lastBox));
  el('rv-area').onclick = () => (inRevit() ? Host.postToHost({ type: 'overview', level: currentLevel() })
    : startCrop({ crop_default: lastBox }));

  /* ── the plan's two modes: Plan (rooms, colours) and Top view (the 3D from above, drawn once as a picture under the overlays) ── */
  let mode = 'plan', pendingTop = false;

  const haveMeshes = () => !!(state.geometry && state.geometry.meshes && state.geometry.meshes.length);

  function underlayLayer() {
    if (!gRoot) return null;
    let g = el('rv-under');
    if (!g || !g.isConnected) {
      g = document.createElementNS(SVG, 'g');
      g.id = 'rv-under';
      g.setAttribute('pointer-events', 'none');
      gRoot.insertBefore(g, gRoot.firstChild);         // under everything the page and this file draw
    }
    return g;
  }

  /* The model from straight above, cut at the level's height so ceilings and roofs do not hide the rooms, as one picture. */
  function renderTopView(retry = true) {
    // The page builds its 3D scene on an animation frame, which does not run in a background tab: build it now if it is missing.
    if (typeof threeScene !== 'undefined' && !threeScene && typeof ensureScene === 'function') { try { ensureScene(); } catch (e) { console.error('revit-shell scene', e); } }
    const b = state.bounds, g = underlayLayer();
    if (!b || !g || !window.THREE || typeof threeRenderer === 'undefined' || !threeRenderer || !threeScene) {
      if (retry) setTimeout(() => { if (mode === 'top') renderTopView(false); }, 400);          // the scene may still be starting
      return;
    }
    const cam = topCamera(b, state.unitsToMetres || 1), size = imageSize(b, 2048), place = underlayPlacement(b);
    const cut = clipHeight(levelElevationM(), CUT_M);
    const ortho = new THREE.OrthographicCamera(-cam.width / 2, cam.width / 2, cam.height / 2, -cam.height / 2, 0.1, 1000);
    ortho.position.set(cam.cx, cut + 200, cam.cz);                 // well above the cut, well inside the scene's far range
    ortho.up.set(0, 0, -1);                            // screen up = -z, so plan y runs down the picture as in the SVG
    ortho.lookAt(cam.cx, cut, cam.cz);
    const off = hiddenTypes(), restore = [];
    threeScene.traverse(o => {
      if (!o.visible) return;
      if ((o.isMesh && off.has(o.userData.meshType)) || o.isSprite) { restore.push(o); o.visible = false; }
    });
    const prev = threeRenderer.getSize(new THREE.Vector2()), ratio = threeRenderer.getPixelRatio();
    threeRenderer.setPixelRatio(1);
    threeRenderer.setSize(size.w, size.h, false);
    const fog = threeScene.fog;
    threeScene.fog = null;                                         // the scene's fog would paint a high camera's whole view as background
    threeRenderer.clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, -1, 0), cut)];
    threeRenderer.render(threeScene, ortho);
    threeScene.fog = fog;
    const url = threeRenderer.domElement.toDataURL('image/png');
    threeRenderer.clippingPlanes = [];
    threeRenderer.setPixelRatio(ratio);
    threeRenderer.setSize(prev.x, prev.y, false);
    restore.forEach(o => { o.visible = true; });
    g.innerHTML = `<image href="${url}" x="${place.x}" y="${place.y}" width="${place.width}" height="${place.height}" preserveAspectRatio="none"/>`;
  }

  function applyMode() {
    document.querySelectorAll('#rv-modes button').forEach(btn => btn.classList.toggle('on', btn.dataset.mode === mode));
    const under = underlayLayer(), top = mode === 'top' && haveMeshes();
    if (top) renderTopView();
    // The plan's own drawing (walls, doors, room fills) is every child of the root except the layers this file and the page's
    // overlays own; Top view hides it so the picture shows, Plan mode shows it again.
    const keep = new Set(['rv-under', 'rv-extras', 'rv-here', 'rv-crop', 'route-overlay']);
    if (gRoot) for (const child of gRoot.children) if (!keep.has(child.id)) child.style.display = top ? 'none' : '';
    if (under) under.style.display = top ? '' : 'none';
  }

  function setMode(next) {
    if (next === 'top' && !haveMeshes()) {                 // the 3D is only read when it is first wanted
      pendingTop = true;
      sendRead(meshRequest(currentLevel(), lastBox));
      return;
    }
    mode = next;
    applyMode();
  }
  document.querySelectorAll('#rv-modes button').forEach(btn => { btn.onclick = () => setMode(btn.dataset.mode); });

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

  const withMeshes = message => (wantsMeshes(mode, previewOn) ? { ...message, meshes: true } : message);   // the preview pane and the Top view need the 3D

  el('rv-crop-ok').onclick = () => {
    if (!isUsable(cropRect)) { toast('Drag a bigger frame around the area first', 'inf'); return; }
    lastBox = toModelBox(cropRect);
    sendRead(withMeshes({ type: 'readModel', level: currentLevel(), crop: lastBox }));
  };
  el('rv-crop-all').onclick = () => {
    lastBox = null;
    sendRead(withMeshes({ type: 'readModel', level: currentLevel() }));
  };
  el('rv-crop-cancel').onclick = () => sendRead(withMeshes({ type: 'readModel', level: currentLevel(), crop: lastBox }));   // back to the area it had

  if (new URLSearchParams(window.location.search).get('demo') === '1') {
    loadDemo().then(() => { ensureLoop(); });          // development without Revit: the demo plan stands in for a model
  }
  if (new URLSearchParams(window.location.search).get('demo') === 'crop') {
    loadDemo().then(() => { ensureLoop(); startCrop({}); });
  }

  /* ── what the path means, on the plan: a view cone at every point, rings where the camera pauses ── */
  let lastPlan = null;                    // the latest /api/camera-plan, for the pause rings

  function extrasLayer() {
    if (!gRoot) return null;
    let g = el('rv-extras');
    if (!g || !g.isConnected) {
      g = document.createElementNS(SVG, 'g');
      g.id = 'rv-extras';
      g.setAttribute('pointer-events', 'none');
      const route = el('route-overlay');
      gRoot.insertBefore(g, route || null);             // just under the points, over the plan
    }
    return g;
  }

  function drawPlanExtras() {
    const g = extrasLayer();
    if (!g) return;
    const wps = state.waypoints, len = coneLength(state.bounds), k = circleR();
    const parts = [];
    wps.forEach((w, i) => {
      const f = nearestFrame(p3.frames, w.x, w.y);
      if (!f) return;
      const [apex, a, b] = viewCone(w.x, w.y, f.yaw, cam.fov, len);
      const colour = i === state.selectedWp ? '#d99000' : w.invalid ? '#f0b429' : '#2f6bff';
      parts.push(`<polygon points="${apex} ${a} ${b}" fill="${colour}" fill-opacity="${i === state.selectedWp ? 0.3 : 0.16}" stroke="${colour}" stroke-opacity=".7" stroke-width="${k * 0.12}"/>`);
    });
    for (const p of pauseKeyframes(lastPlan)) {
      parts.push(`<circle cx="${p.x}" cy="${p.y}" r="${k * 2}" fill="none" stroke="#d99000" stroke-width="${k * 0.3}" stroke-dasharray="${k * 0.6} ${k * 0.5}"/>`);
    }
    g.innerHTML = parts.join('');
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
    const here = frameAt(p3.frames, t), x = here.x, y = here.y, yaw = here.yaw;
    const r = circleR() * 1.3, [apex, c1, c2] = viewCone(x, y, yaw, cam.fov, r * 6);
    g.innerHTML =
      `<polygon points="${apex} ${c1} ${c2}" fill="#d64545" fill-opacity=".22" stroke="#d64545" stroke-opacity=".6" stroke-width="${r * 0.12}"/>` +
      `<circle cx="${x}" cy="${y}" r="${r}" fill="#d64545" stroke="#fff" stroke-width="${r * 0.3}"/>`;
  }
  wrap('updateCameraFromT', drawHere);

  /* ── the 3D preview pane (first-person view along the path, beside the plan) ── */
  document.body.classList.add('rv-preview-on');
  const empty = el('p3d-empty');
  if (empty) empty.innerHTML = '<div>Draw at least two points<br>to see the walk here</div>';
  const refit = () => { if (previewOn && typeof resize3D === 'function' && el('preview-3d').classList.contains('visible')) resize3D(); };
  if (window.ResizeObserver) new ResizeObserver(refit).observe(el('preview-3d'));
  function setPreview(on) {
    previewOn = on;
    document.body.classList.toggle('rv-preview-on', on);
    el('rv-prev').classList.toggle('primary', on);
    el('rv-prev').setAttribute('aria-pressed', String(on));
    if (on && inRevit() && loadedOnce && !haveMeshes()) sendRead(meshRequest(currentLevel(), lastBox));   // the 3D was not read yet
    requestAnimationFrame(refit);
  }
  el('rv-prev').onclick = () => setPreview(!previewOn);

  /* ── EXPERIMENTAL Revit camera: the active Revit 3D view follows the play head (about 15 poses a second) ── */
  const FEET_M = 0.3048;
  let camOn = false;
  const camThrottle = makeThrottle(66, () => performance.now());
  let camTimer = null;
  const sendCamera = pose => { if (pose) Host.postToHost(pose); };
  function setCamera(on, note) {
    camOn = on;
    el('rv-cam').classList.toggle('primary', on);
    el('rv-cam').setAttribute('aria-pressed', String(on));
    const n = el('rv-cam-note');
    n.textContent = note || '';
    n.hidden = !note;
    if (on && !camTimer) camTimer = setInterval(() => sendCamera(camThrottle.take()), 33);   // sends the held pose once its time comes
    if (!on && camTimer) { clearInterval(camTimer); camTimer = null; }
  }
  function followInRevit(t) {
    if (!camOn) return;
    if (!cameraAllowed(state.source, inRevit())) {                  // a JSON plan was loaded: it has no Revit coordinates
      Host.postToHost({ type: 'cameraStop' });
      setCamera(false, 'The Revit camera needs a model read from Revit.');
      return;
    }
    if (!p3.frames || !p3.frames.length) return;
    const f = frameAt(p3.frames, t);
    const u = (state.unitsToMetres || 1) / FEET_M;                  // plan units -> Revit feet
    sendCamera(camThrottle.push(cameraMessage({ x: f.x * u, y: f.y * u, yaw: f.yaw }, levelElevationM() / FEET_M)));
  }
  wrap('updateCameraFromT', followInRevit);
  if (inRevit()) {
    el('rv-cam').hidden = false;
    el('rv-cam').onclick = () => {
      if (camOn) { Host.postToHost({ type: 'cameraStop' }); setCamera(false); return; }
      if (!cameraAllowed(state.source, inRevit())) { setCamera(false, 'The Revit camera needs a model read from Revit.'); return; }
      Host.postToHost({ type: 'cameraStart' });
      camThrottle.reset();
      setCamera(true, 'Revit camera on: press play');
    };
    // Revit could not start or keep going (no 3D view, locked, isometric, ...): switch it off and say why
    Host.handlers.cameraError = msg => setCamera(false, String(msg.message || 'The Revit camera stopped.'));
  }

  /* ── selection shared with the page's own plan selection ── */
  sel.subscribe(id => {
    const i = id && id.startsWith('wp:') ? Number(id.slice(3)) : null;
    if (state.selectedWp !== i) { state.selectedWp = i; renderRoute(); }
    drawPlanExtras();
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
      '<div class="rv-fld">Eye height<input value="1.57 m" readonly></div>' +
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
    const tl = p3.timeline, u = state.unitsToMetres || 1;
    return state.waypoints.map((w, i) => {
      const m = projectToRoute(p3.frames, p3.dists, u, w.x, w.y);
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
    lastPlan = await r.json();
    drawPlanExtras();
    const tracks = buildTracks({ plan: lastPlan, frames: p3.frames, plain: true });
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
    el('rv-save').disabled = state.waypoints.length < 2;
    if (!state.waypoints.length) { lastPlan = null; const h = el('rv-here'); if (h) h.innerHTML = ''; }
    pageToSelection();
    drawPlanExtras();
    schedulePreview();
  });
  wrap('renderTimelineLanes', renderLanes);
  wrap('updateWpList', () => {
    document.querySelectorAll('#wp-list .wp-row').forEach((row, i) => row.classList.toggle('rv-invalid', !!(state.waypoints[i] && state.waypoints[i].invalid)));
  });
})();
