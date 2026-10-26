/* Physically based materials for the 3D preview: one look per surface finish (see frontend/assets/CREDITS.md).
   Texture maps are desaturated and normalised to a linear mean of MAP_MEAN, so a material keeps its design colour
   and the finish's roughness on average once the maps land. */

const MAP_MEAN = 0.5;
const LIGHT_GLOW = 2.5;

const FINISH_LOOKS = {
  carpet:   { maps: 'carpet',   tileM: 3.0, roughness: 0.95, metalness: 0, tint: null },
  wood:     { maps: 'wood',     tileM: 1.8, roughness: 0.5,  metalness: 0, tint: null },
  concrete: { maps: 'concrete', tileM: 2.0, roughness: 0.4,  metalness: 0, tint: null },
  plaster:  { maps: 'plaster',  tileM: 2.0, roughness: 0.9,  metalness: 0, tint: null },
  oak:      { maps: 'oak',      tileM: 0.8, roughness: 0.55, metalness: 0, tint: null },
  laminate: { maps: 'laminate', tileM: 1.0, roughness: 0.45, metalness: 0, tint: null },
  fabric:   { maps: 'fabric',   tileM: 0.3, roughness: 0.95, metalness: 0, tint: null },
  metal:    { maps: 'metal',    tileM: 0.5, roughness: 0.35, metalness: 0.7, tint: null },
  steel:    { maps: 'steel',    tileM: 0.5, roughness: 0.25, metalness: 0.8, tint: null },
  plastic:  { maps: 'plastic',  tileM: 0.3, roughness: 0.45, metalness: 0, tint: null },
  ceramic:  { maps: 'ceramic',  tileM: 0.3, roughness: 0.8,  metalness: 0, tint: null },
  foliage:  { maps: 'foliage',  tileM: 1.5, roughness: 0.75, metalness: 0, tint: null },
  glass:    { maps: null, tileM: 1, roughness: 0.05, metalness: 0, tint: null, physical: { transmission: 1, ior: 1.5, thickness: 0.01 } },
  screen:   { maps: null, tileM: 1, roughness: 0.2,  metalness: 0.2, tint: null },
  ceiling:  { maps: null, tileM: 1, roughness: 0.95, metalness: 0, tint: null },
  light:    { maps: null, tileM: 1, roughness: 1,    metalness: 0, tint: null },
  plain:    { maps: null, tileM: 1, roughness: 0.8,  metalness: 0, tint: null },
};

const TYPE_FINISHES = { wall: 'plaster', floor: 'concrete', glass: 'glass', window: 'glass', frame: 'metal', ceiling: 'ceiling', light: 'light' };

/* The mesh's finish, or one that fits its type when the source (e.g. an IFC model) gave none or one we have no look for. */
function finishFor(mesh) {
  return FINISH_LOOKS[mesh.finish] ? mesh.finish : TYPE_FINISHES[mesh.type] || 'plain';
}

/* Box-mapped texture coordinates in metres / tileM: each vertex is projected onto the plane its normal faces most. */
function boxUV(positions, normals, tileM) {
  const uv = new Float32Array(positions.length / 3 * 2);
  for (let i = 0; i < positions.length / 3; i++) {
    const [x, y, z] = positions.subarray(i * 3, i * 3 + 3);
    const [ax, ay, az] = Array.from(normals.subarray(i * 3, i * 3 + 3), Math.abs);
    const [u, v] = ay >= ax && ay >= az ? [x, z] : ax >= az ? [z, y] : [x, y];
    uv[i * 2] = u / tileM;
    uv[i * 2 + 1] = v / tileM;
  }
  return uv;
}

/* A shaded material for a mesh-like {type, finish, color, opacity}. textures(folder) resolves the folder's
   {map, normalMap, roughnessMap}; until it does the material shows its plain colour. */
function makeMaterial(mesh, textures) {
  const look = FINISH_LOOKS[finishFor(mesh)];
  const color = new THREE.Color(mesh.color);
  if (look.physical) {
    return new THREE.MeshPhysicalMaterial({
      color: color.lerp(new THREE.Color(0xffffff), 0.75), roughness: look.roughness, metalness: look.metalness,
      side: THREE.DoubleSide, ...look.physical,
    });
  }
  if (look === FINISH_LOOKS.light) {
    return new THREE.MeshStandardMaterial({ color: 0x000000, emissive: color, emissiveIntensity: LIGHT_GLOW, side: THREE.DoubleSide });
  }
  if (look.tint) color.multiply(new THREE.Color(look.tint));
  const opacity = mesh.opacity ?? 1;
  const mat = new THREE.MeshStandardMaterial({
    color, roughness: look.roughness, metalness: look.metalness, side: THREE.DoubleSide,
    transparent: opacity < 1, opacity, depthWrite: opacity >= 1,
  });
  if (look.maps) {
    textures(look.maps).then(maps => {
      Object.assign(mat, maps);
      mat.color.multiplyScalar(1 / MAP_MEAN);
      mat.roughness = look.roughness / MAP_MEAN;
      mat.needsUpdate = true;
    }, () => {});
  }
  return mat;
}

if (typeof module === 'object') module.exports = { FINISH_LOOKS, finishFor, boxUV, makeMaterial };
