const {test} = require('node:test');
const assert = require('node:assert/strict');
const {AvatarState, validateCues, cueAt, estimateCues} = require('./core.js');

test('token completion never ends audio or destroys idle', () => {
  const state = new AvatarState();
  state.setActivity('thinking'); state.playback(true); state.generationEnded();
  assert.equal(state.value, 'speaking');
  state.playback(false); assert.equal(state.value, 'idle');
  state.setActivity('listening'); state.stop(); assert.equal(state.value, 'idle');
});
test('timeline uses media clock, including seek backwards, silence and gaps', () => {
  const cues = validateCues([{start: .1, end: .3, value: 'A'}, {start: .5, end: 1, value: 'D'}]);
  assert.equal(cueAt(cues, .6), 'D');
  assert.equal(cueAt(cues, .2), 'A');
  for (const time of [0, .3, .4, 1, 200]) assert.equal(cueAt(cues, time), 'X');
});
test('reject malformed, overlapping and prototype-shaped cues', () => {
  for (const value of ['bad', '__proto__', 'constructor'])
    assert.throws(() => validateCues([{start: 0, end: 1, value}]));
  assert.throws(() => validateCues([{start: 1, end: .5, value: 'A'}]));
  assert.throws(() => validateCues([{start: 0, end: Infinity, value: 'A'}]));
  assert.throws(() => validateCues([{start: 0, end: 2, value: 'A'}, {start: 1, end: 3, value: 'A'}]));
});
test('text fallback distinguishes closed, rounded, open and silence shapes', () => {
  const cues = estimateCues('мау ', 1);
  assert.deepEqual(cues.map(c => c.value), ['A', 'D', 'F', 'X']);
  assert.equal(cues.at(-1).end, 1);
});
