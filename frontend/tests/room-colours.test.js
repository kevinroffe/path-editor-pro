const test = require('node:test');
const assert = require('node:assert/strict');
const { roomColour } = require('../js/room-colours.js');

const cases = [
  ['Open Space WorkStation', '#a4c2f4'],
  ['Bench', '#a4c2f4'],
  ['Conference', '#c9f5dd'],
  ['Boardroom', '#c9f5dd'],
  ['Kitchen', '#f9d8b6'],
  ['Comfort Zone', '#fde4a0'],
  ['Wellness', '#fde4a0'],
  ['Reception', '#e6d6fa'],
  ['IT Room', '#c8b896'],
  ['Storage Room', '#fde9b5'],
  ['Print', '#fde9b5'],
  ['Phone Booth', '#fdf1d0'],
  ['Office - Non Receiving Guests', '#cfe1fb'],
];
for (const [type, hex] of cases) test(`${type} is ${hex}`, () => assert.equal(roomColour(type), hex));

test('unknown types stay uncoloured', () => assert.equal(roomColour('Shaft'), null));
test('"Kitchenette" is still a kitchen, "Edit" is not IT', () => {
  assert.equal(roomColour('Kitchenette'), '#f9d8b6');
  assert.equal(roomColour('Edit suite'), null);
});
