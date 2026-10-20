/* Preview-only video settings: title card text, music theme, volume and fades, plus brand prefs kept per machine. */

const THEMES = [
  { id: 'premium-lobby', name: 'Premium lobby', sub: 'Warm piano, soft pads' },
  { id: 'modern-workspace', name: 'Modern workspace', sub: 'Light electronic pulse' },
  { id: 'bright-leasing', name: 'Bright leasing', sub: 'Upbeat, optimistic' },
  { id: 'cinematic-reveal', name: 'Cinematic reveal', sub: 'Slow swell to the end' },
];

const CARD_COLOURS = [
  { id: 'charcoal', name: 'Charcoal', hex: '#1e2430' },
  { id: 'blue', name: 'qbiq blue', hex: '#2f6bff' },
  { id: 'teal', name: 'Teal', hex: '#5b8a8c' },
  { id: 'sand', name: 'Sand', hex: '#c9b79c' },
];

const BRAND_KEY = 'pathEditor.brand';
const MAX_TEXT = 120;
const MAX_FADES = 20;
const MAX_LOGO_BYTES = 1_572_864;
const LOGO_TYPES = ['image/png', 'image/svg+xml'];

function defaultVideo() {
  return { name: '', tagline: '', outro: '', theme: 'premium-lobby', volume: 0.7, fades: [] };
}

const cleanText = v => (typeof v === 'string' ? v.trim().slice(0, MAX_TEXT) : '');
const isTheme = id => THEMES.some(t => t.id === id);
const isColour = id => CARD_COLOURS.some(c => c.id === id);

/* Video settings from untrusted input (a loaded path file), with every field repaired. */
function cleanVideo(raw) {
  const d = defaultVideo(), r = raw && typeof raw === 'object' ? raw : {};
  const fades = (Array.isArray(r.fades) ? r.fades : [])
    .map(f => ({ outM: Number(f?.outM), inM: Number(f?.inM) }))
    .filter(f => Number.isFinite(f.outM) && Number.isFinite(f.inM) && f.outM >= 0 && f.outM < f.inM)
    .sort((a, b) => a.outM - b.outM)
    .slice(0, MAX_FADES);
  return {
    name: cleanText(r.name),
    tagline: cleanText(r.tagline),
    outro: cleanText(r.outro),
    theme: isTheme(r.theme) ? r.theme : d.theme,
    volume: typeof r.volume === 'number' && Number.isFinite(r.volume) ? Math.min(1, Math.max(0, r.volume)) : d.volume,
    fades,
  };
}

/* Why a logo file is refused, or null when it is fine. */
function acceptLogo(file) {
  if (!LOGO_TYPES.includes(file?.type)) return 'Use a PNG or SVG logo.';
  if (file.size > MAX_LOGO_BYTES) return 'That logo is over 1.5 MB. Use a smaller file.';
  return null;
}

function defaultBrandPrefs() {
  return { logo: null, logoName: '', colour: 'charcoal', theme: 'premium-lobby' };
}

/* Last-used logo, card colour and theme on this machine; defaults when storage is missing or blocked. */
function loadBrandPrefs(storage) {
  const d = defaultBrandPrefs();
  try {
    const p = JSON.parse(storage?.getItem(BRAND_KEY) || 'null') || {};
    return {
      logo: typeof p.logo === 'string' && p.logo.startsWith('data:image/') ? p.logo : d.logo,
      logoName: typeof p.logoName === 'string' ? p.logoName : d.logoName,
      colour: isColour(p.colour) ? p.colour : d.colour,
      theme: isTheme(p.theme) ? p.theme : d.theme,
    };
  } catch {
    return d;
  }
}

function saveBrandPrefs(storage, prefs) {
  try {
    storage?.setItem(BRAND_KEY, JSON.stringify(prefs));
  } catch {
    /* storage full or blocked: prefs just aren't remembered */
  }
}

if (typeof module === 'object') {
  module.exports = {
    THEMES, CARD_COLOURS, defaultVideo, cleanVideo, acceptLogo, loadBrandPrefs, saveBrandPrefs,
  };
}
