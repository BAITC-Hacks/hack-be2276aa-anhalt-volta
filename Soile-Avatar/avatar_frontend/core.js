/* Provider-independent state and timeline. Also importable by node:test. */
(function (root) {
  'use strict';
  const shapes = {
    X: [24, 2, 0, 0], A: [23, 1, 0, 0], B: [27, 7, 1, 0],
    C: [29, 15, .7, .2], D: [27, 26, .5, .6], E: [20, 17, .3, .3],
    F: [13, 13, 0, 0], G: [25, 5, 1, 0], H: [26, 12, .7, 1]
  };
  function validateCues(payload) {
    const cues = Array.isArray(payload) ? payload : payload?.mouthCues;
    if (!Array.isArray(cues) || cues.length > 100000) throw Error('Нужен массив mouthCues');
    let previous = 0;
    return cues.map(c => {
      if (!c || !Number.isFinite(c.start) || !Number.isFinite(c.end) ||
          c.start < previous || c.end <= c.start || c.end > 3600 || !Object.hasOwn(shapes, c.value))
        throw Error('Некорректные visemes: A–H/X, интервалы в секундах, без пересечений');
      previous = c.end;
      return {start: c.start, end: c.end, value: c.value};
    });
  }
  function cueAt(cues, time) {
    let lo = 0, hi = cues.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1, c = cues[mid];
      if (time < c.start) hi = mid - 1;
      else if (time >= c.end) lo = mid + 1;
      else return c.value;
    }
    return 'X';
  }
  function letterShape(letter) {
    const c = letter.toLowerCase();
    if (/[мбпmbp]/u.test(c)) return 'A';
    if (/[фвfv]/u.test(c)) return 'G';
    if (/[аәяah]/u.test(c)) return 'D';
    if (/[оөёo]/u.test(c)) return 'E';
    if (/[уұүюuwq]/u.test(c)) return 'F';
    if (/[иіыейэei]/u.test(c)) return 'C';
    if (/[лl]/u.test(c)) return 'H';
    return /\p{L}/u.test(c) ? 'B' : 'X';
  }
  function estimateCues(text, duration) {
    // Grapheme approximation, deliberately not advertised as phoneme recognition.
    const chars = Array.from(text), step = duration / Math.max(chars.length, 1);
    return chars.map((c, i) => ({start: i * step, end: (i + 1) * step, value: letterShape(c)}));
  }
  class AvatarState {
    constructor() { this.activity = 'idle'; this.audioPlaying = false; }
    setActivity(value) {
      if (!['idle', 'listening', 'thinking'].includes(value)) throw Error('Invalid activity');
      this.activity = value;
    }
    get value() { return this.audioPlaying ? 'speaking' : this.activity; }
    playback(started) { this.audioPlaying = started; }
    generationEnded() { this.activity = 'idle'; } // Audio owns speaking, never tokens.
    stop() { this.audioPlaying = false; this.activity = 'idle'; }
  }
  const api = {shapes, validateCues, cueAt, letterShape, estimateCues, AvatarState};
  if (typeof module !== 'undefined') module.exports = api;
  else root.AvatarCore = api;
})(globalThis);
