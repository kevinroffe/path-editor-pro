const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { FINISH_LOOKS, finishFor, boxUV, makeMaterial } = require('../js/materials3d.js');

const ROOT = path.join(__dirname, '..', '..');
const TEXTURES = path.join(ROOT, 'frontend', 'assets', 'textures');
const VOCABULARY = ['carpet', 'wood', 'concrete', 'plaster', 'glass', 'metal', 'steel', 'oak', 'laminate', 'fabric',
  'plastic', 'foliage', 'ceramic', 'screen', 'ceiling', 'light', 'plain'];
const TEXTURED = ['carpet', 'wood', 'concrete', 'plaster', 'oak', 'laminate', 'fabric', 'metal', 'steel', 'plastic', 'ceramic', 'foliage'];

/* Two triangles of a quad with the given corners, and its normal repeated per vertex. */
function quad(corners, normal) {
  const tris = [0, 1, 2, 0, 2, 3].flatMap(i => corners[i]);
  return { positions: new Float32Array(tris), normals: new Float32Array(Array(6).fill(normal).flat()) };
}
const range = (uv, k) => { const v = [...uv].filter((_, i) => i % 2 === k); return [Math.min(...v), Math.max(...v)]; };

test('a mesh keeps the finish the backend gave it', () => {
  assert.equal(finishFor({ type: 'furniture', finish: 'fabric' }), 'fabric');
  assert.equal(finishFor({ type: 'wall', finish: 'glass' }), 'glass');
});

test('a finish with no look falls back by type', () => {
  assert.equal(finishFor({ type: 'wall', finish: 'marble' }), 'plaster');
  assert.equal(finishFor({ type: 'furniture', finish: 'velvet' }), 'plain');
});

test('makeMaterial builds a plain material for a finish with no look', () => {
  class Color { multiply() { return this; } lerp() { return this; } multiplyScalar() { return this; } }
  class MeshStandardMaterial { constructor(o) { Object.assign(this, o); } }
  globalThis.THREE = { Color, MeshStandardMaterial, MeshPhysicalMaterial: MeshStandardMaterial, DoubleSide: 2 };
  try {
    const mat = makeMaterial({ type: 'furniture', finish: 'velvet', color: '#808080' }, () => assert.fail('no maps to load'));
    assert.equal(mat.roughness, FINISH_LOOKS.plain.roughness);
  } finally {
    delete globalThis.THREE;
  }
});

test('meshes without a finish fall back by type', () => {
  const cases = { wall: 'plaster', floor: 'concrete', glass: 'glass', window: 'glass', frame: 'metal', ceiling: 'ceiling',
    light: 'light', furniture: 'plain', door: 'plain', other: 'plain' };
  for (const [type, finish] of Object.entries(cases)) assert.equal(finishFor({ type }), finish, type);
});

test('every finish the backend can send has a look', () => {
  const src = fs.readFileSync(path.join(ROOT, 'backend', 'qbiq_scene3d.py'), 'utf8');
  const sent = [...src.matchAll(/finish="(\w+)"/g)].map(m => m[1]);
  assert.ok(sent.length > 10, 'found the backend materials');
  for (const f of new Set([...VOCABULARY, ...sent])) assert.ok(FINISH_LOOKS[f], f);
});

test('the real surfaces are textured, the rest are plain colour', () => {
  for (const f of TEXTURED) assert.equal(typeof FINISH_LOOKS[f].maps, 'string', f);
  for (const f of ['ceiling', 'screen', 'light', 'glass', 'plain']) assert.equal(FINISH_LOOKS[f].maps, null, f);
});

test('every texture folder holds albedo, normal and roughness maps', () => {
  for (const [f, look] of Object.entries(FINISH_LOOKS).filter(([, l]) => l.maps)) {
    for (const map of ['albedo', 'normal', 'roughness']) {
      assert.ok(fs.existsSync(path.join(TEXTURES, look.maps, `${map}.jpg`)), `${f}: ${look.maps}/${map}.jpg`);
    }
    assert.ok(look.tileM > 0, `${f} tileM`);
  }
});

test('looks are physically plausible', () => {
  for (const [f, look] of Object.entries(FINISH_LOOKS)) {
    assert.ok(look.roughness >= 0 && look.roughness <= 1, `${f} roughness`);
    assert.ok(look.metalness >= 0 && look.metalness <= 1, `${f} metalness`);
    assert.ok(look.tint === null || /^#[0-9a-f]{6}$/.test(look.tint), `${f} tint`);
  }
});

test('glass is clear transmissive glass', () => {
  const g = FINISH_LOOKS.glass;
  assert.equal(g.physical.transmission, 1);
  assert.equal(g.physical.ior, 1.5);
  assert.equal(g.physical.thickness, 0.01);
  assert.equal(g.roughness, 0.05);
});

test('boxUV maps a floor quad onto (x, z) at real-world scale', () => {
  const { positions, normals } = quad([[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]], [0, 1, 0]);
  const uv = boxUV(positions, normals, 2);
  assert.equal(uv.length, 12);
  assert.deepEqual(range(uv, 0), [0, 1]);
  assert.deepEqual(range(uv, 1), [0, 1]);
});

test('boxUV maps a quad facing +X onto (z, y)', () => {
  const { positions, normals } = quad([[5, 0, 0], [5, 0, 1], [5, 3, 1], [5, 3, 0]], [1, 0, 0]);
  const uv = boxUV(positions, normals, 1);
  assert.deepEqual(range(uv, 0), [0, 1], 'u follows z');
  assert.deepEqual(range(uv, 1), [0, 3], 'v follows y');
});

test('boxUV maps a quad facing -Z onto (x, y), choosing the dominant axis of a tilted normal', () => {
  const { positions, normals } = quad([[0, 0, 4], [1, 0, 4], [1, 2, 4], [0, 2, 4]], [0.3, 0.2, -0.9]);
  const uv = boxUV(positions, normals, 0.5);
  assert.deepEqual(range(uv, 0), [0, 2], 'u follows x');
  assert.deepEqual(range(uv, 1), [0, 4], 'v follows y');
});
