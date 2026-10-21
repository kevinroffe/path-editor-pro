/* Plan fill colour for a room, by its type — the soft program colours of a qbiq test fit. */

const ROOM_COLOURS = [
  [/work ?station|open space|bench|desk/i, '#a4c2f4'],
  [/conference|meeting|board|focus|huddle/i, '#c9f5dd'],
  [/kitchen|pantry|caf[eé]|break/i, '#f9d8b6'],
  [/comfort|lounge|wellness|game|relax/i, '#fde4a0'],
  [/reception|lobby|waiting/i, '#e6d6fa'],
  [/\bit\b|server/i, '#c8b896'],
  [/storage|print|copy|locker|clean|janitor/i, '#fde9b5'],
  [/phone|booth|\bopen\b/i, '#fdf1d0'],
  [/office/i, '#cfe1fb'],
];

/* First matching colour for a room type, or null to leave it uncoloured. */
function roomColour(type) {
  return ROOM_COLOURS.find(([re]) => re.test(type || ''))?.[1] ?? null;
}

if (typeof module === 'object') module.exports = { ROOM_COLOURS, roomColour };
