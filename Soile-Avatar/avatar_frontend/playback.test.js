/* Exercise real controller callbacks with deterministic media/TTS events. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function controller() {
  class Element {
    constructor() { this.value = ''; this.style = {}; this.dataset = {}; this.listeners = {}; this.attributes = {}; }
    addEventListener(event, fn) { (this.listeners[event] ??= []).push(fn); }
    emit(event) { for (const fn of this.listeners[event] || []) fn({}); }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key]; }
    removeAttribute(key) { delete this.attributes[key]; }
    getBoundingClientRect() { return {height: 700, width: 1000, left: 0, top: 0}; }
    replaceChildren() {} append() {} load() {}
    pause() { this.emit('pause'); }
    async play() { this.emit('playing'); }
  }
  const elements = new Map(), get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  let now = 0, frame, callbacks = {}, currentSpeech;
  const parent = {postMessage() {}};
  const window = {parent, addEventListener(name, fn) { callbacks[name] = fn; },
    speechSynthesis: {getVoices: () => [], addEventListener() {}, cancel() {}, speak(u) { currentSpeech = u; }}
  };
  const sandbox = vm.createContext({window, document: {getElementById: get,
    querySelector: get, querySelectorAll: () => [], createElement: () => new Element()},
    performance: {now: () => now}, matchMedia: () => ({matches: false}),
    ResizeObserver: class { observe() {} }, SpeechSynthesisUtterance: class { constructor(text) {this.text = text;} },
    requestAnimationFrame(fn) { frame = fn; }, URL: {revokeObjectURL() {}}, console,
  });
  for (const file of ['core.js', 'avatar.js'])
    vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), sandbox);
  get('shape').value = 'auto';
  return {avatar: window.avatar, get, speech: () => currentSpeech,
    render(args) { callbacks.message({source: parent, data: {type: 'streamlit:render', args}}); },
    tick(ms) {now = ms; frame(ms);}
  };
}

test('host rerenders preserve playing speech; stale callbacks cannot revive it after stop', () => {
  const c = controller();
  c.render({reset_id: 1, state: 'thinking'});
  c.avatar.speak('Привет'); const old = c.speech(); old.onstart();
  c.render({reset_id: 1, state: 'idle'});
  assert.equal(c.avatar.getState(), 'speaking');
  c.tick(100); c.avatar.stop(); old.onstart(); old.onend();
  assert.equal(c.avatar.getState(), 'idle');
  c.tick(200);
  assert.match(c.get('state').textContent, /idle/);
});

test('duplicate reply IDs do not restart TTS; reset cancels speech', () => {
  const c = controller(); c.get('autoplay').checked = true;
  const args = {reset_id: 1, reply_id: 'one', reply: 'Привет', state: 'idle'};
  c.render(args); const first = c.speech(); first.onstart();
  c.render(args); assert.equal(c.speech(), first);
  c.render({...args, reply_id: '', reply: '', reset_id: 2});
  assert.equal(c.avatar.getState(), 'idle');
});

test('audio queue drains after token completion, and pause closes speaking state', async () => {
  const c = controller();
  const chunk = {src: 'data:audio/wav;base64,AAAA', cues: [{start: 0, end: 1, value: 'D'}]};
  c.avatar.enqueueAudio(chunk); c.avatar.enqueueAudio(chunk);
  c.avatar.generationEnded(); assert.equal(c.avatar.getState(), 'speaking');
  c.get('audio').emit('ended'); assert.equal(c.avatar.getState(), 'speaking');
  c.get('audio').pause(); assert.equal(c.avatar.getState(), 'idle');
  c.get('audio').emit('playing'); c.get('audio').emit('ended');
  assert.equal(c.avatar.getState(), 'idle');
});
