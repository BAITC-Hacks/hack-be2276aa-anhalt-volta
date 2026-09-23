/* Rendering lives for the lifetime of the component, independently of Streamlit reruns. */
'use strict';
const {shapes, validateCues, cueAt, estimateCues, AvatarState} = AvatarCore;
const $ = id => document.getElementById(id);
const state = new AvatarState(), audio = $('audio');
const synth = window.speechSynthesis;
let args = {}, lastReplyId = null, lastAudioId = null, resetId = null;
let cues = [], cueMode = 'amplitude', objectURL = null;
let context, analyser, samples, utterance, ttsCues = [], ttsOrigin = 0;
let generation = 0, queue = [], queueActive = false, pendingSpeech = false;
let previousTime = 0, blinkAt = 2, blinkStart = -10, gazeAt = 0, gx = 0, gy = 0;
let yaw = 0, pitch = 0, roll = 0, mouth = [...shapes.X], lastState = '';
let manualUntil = 0, manualState = 'idle';
const layers = [...document.querySelectorAll('[data-depth]')];
const eyes = [...document.querySelectorAll('.eye')], pupils = [...document.querySelectorAll('.pupil')];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
$('motion').checked = !reduced.matches;
function notice(text) { $('notice').textContent = text; }
function send(type, payload = {}) {
  if (window.parent !== window) window.parent.postMessage({isStreamlitMessage: true, type, ...payload}, '*');
}
function resize() { send('streamlit:setFrameHeight', {height: Math.ceil(document.querySelector('main').getBoundingClientRect().height) + 4}); }
new ResizeObserver(resize).observe(document.querySelector('main'));

function stop() {
  generation++;
  queue = []; queueActive = false; pendingSpeech = false;
  utterance = null; ttsCues = [];
  if (synth) synth.cancel();
  audio.pause();
  state.stop(); manualUntil = 0;
}
function releaseURL() {
  if (objectURL) URL.revokeObjectURL(objectURL);
  objectURL = null;
}
function loadAudio(src, timeline = [], mode = 'visemes') {
  audio.src = src; cues = validateCues(timeline); cueMode = mode;
  audio.load();
  notice(cueMode === 'visemes' ? 'Visemes: рот следует таймкодам аудио.' : 'Упрощённый режим: рот по громкости. Для артикуляции добавьте visemes JSON.');
}
async function ensureAnalyser() {
  if (!context) {
    context = new (window.AudioContext || window.webkitAudioContext)();
    analyser = context.createAnalyser(); analyser.fftSize = 512;
    context.createMediaElementSource(audio).connect(analyser);
    analyser.connect(context.destination);
    samples = new Uint8Array(analyser.fftSize);
  }
  if (context.state === 'suspended') await context.resume();
}
audio.addEventListener('play', async () => {
  if (utterance || pendingSpeech) {
    generation++; utterance = null; pendingSpeech = false;
    synth?.cancel();
  }
  try { await ensureAnalyser(); }
  catch (_) { notice('Аудио играет; анализ громкости недоступен. Используйте visemes JSON.'); }
});
audio.addEventListener('playing', () => state.playback(true));
audio.addEventListener('pause', () => state.playback(false));
audio.addEventListener('waiting', () => state.playback(false));
audio.addEventListener('ended', () => { state.playback(false); if (queueActive) playNext(); });
audio.addEventListener('error', () => {
  if (!audio.getAttribute('src')) return;
  stop(); notice('Не удалось декодировать аудио. Попробуйте другой WAV/MP3.');
});
async function playNext() {
  if (!queue.length) { queueActive = false; state.generationEnded(); return; }
  const item = queue.shift(); queueActive = true;
  releaseURL(); loadAudio(item.src, item.cues, 'visemes');
  try { await audio.play(); }
  catch (_) { queueActive = false; state.playback(false); notice('Нажмите ▶ в аудиоплеере, чтобы разрешить звук.'); }
}

function voices() {
  if (!synth) { $('speak').disabled = true; notice('В этом браузере нет TTS; используйте WAV/MP3.'); return; }
  const previous = $('voice').value, list = synth.getVoices();
  $('voice').replaceChildren();
  const automatic = document.createElement('option'); automatic.value = ''; automatic.textContent = 'Автоматический голос · RU / KK';
  $('voice').append(automatic);
  for (const voice of list) {
    const option = document.createElement('option'); option.value = voice.voiceURI;
    option.textContent = `${voice.name} · ${voice.lang}`; $('voice').append(option);
  }
  if (list.some(v => v.voiceURI === previous)) $('voice').value = previous;
}
voices(); synth?.addEventListener('voiceschanged', voices);
function speak(text, language = 'ru') {
  if (!synth || !text.trim()) return;
  stop(); const token = generation;
  const u = new SpeechSynthesisUtterance(text.trim().slice(0, 2000));
  const available = synth.getVoices();
  u.lang = language === 'kk' ? 'kk-KZ' : 'ru-RU';
  const selected = available.find(v => v.voiceURI === $('voice').value) || available.find(v => v.lang.toLowerCase().startsWith(u.lang.slice(0, 2)));
  if (selected) { u.voice = selected; u.lang = selected.lang; }
  utterance = u; pendingSpeech = true;
  u.onstart = () => {
    if (token !== generation) return;
    pendingSpeech = false; state.playback(true); ttsOrigin = performance.now() / 1000;
    ttsCues = estimateCues(u.text, u.text.length / 13);
    notice('Браузерный TTS: приблизительная артикуляция по тексту; точные фонемы недоступны.');
  };
  u.onboundary = e => {
    if (token !== generation || e.name !== 'word') return;
    const tail = u.text.slice(e.charIndex), word = tail.match(/^\S+/u)?.[0] || '';
    ttsOrigin = performance.now() / 1000;
    ttsCues = estimateCues(word, Math.max(.12, word.length / 13));
  };
  const finish = () => {
    if (token !== generation) return;
    pendingSpeech = false; utterance = null; ttsCues = []; state.playback(false); state.generationEnded();
  };
  u.onend = () => { finish(); if (token === generation) notice('Готово. Возвращаюсь к idle.'); };
  u.onerror = () => { finish(); if (token === generation) notice('TTS недоступен. Выберите установленный голос или загрузите аудио.'); };
  u.onpause = () => { if (token === generation) state.playback(false); };
  u.onresume = () => { if (token === generation) state.playback(true); };
  synth.speak(u);
}
$('speak').onclick = () => speak($('text').value, args.language);
$('reply').onclick = () => { if (args.reply) { $('text').value = args.reply; speak(args.reply, args.language); } };
$('reply').disabled = true;
$('demo').onclick = async () => {
  stop(); const token = generation;
  try {
    const response = await fetch('demo.json');
    if (!response.ok) throw Error('missing demo');
    const timeline = validateCues(await response.json());
    if (token !== generation) return;
    releaseURL(); loadAudio('demo.wav', timeline, 'visemes');
    document.querySelector('details').open = true;
    await ensureAnalyser();
    if (token !== generation) return;
    await audio.play();
  } catch (_) { if (token === generation) notice('Нажмите ▶ в аудиоплеере. Если демо отсутствует, загрузите свой WAV/MP3.'); }
};
$('stop').onclick = () => { stop(); notice('Остановлено. Idle-анимация продолжается.'); };
for (const name of ['idle', 'listening', 'thinking']) $(name).onclick = () => {
  stop(); manualState = name; manualUntil = performance.now() + 5000;
  state.setActivity(name); notice(name === 'idle' ? 'Idle: готов к разговору.' : 'Демонстрация состояния на 5 секунд; микрофон не включается.');
};
for (const value of Object.keys(shapes)) {
  const option = document.createElement('option'); option.value = value; option.textContent = value;
  $('shape').append(option);
}
$('file').onchange = () => {
  const file = $('file').files[0]; if (!file) return;
  if (file.size > 20 * 1024 * 1024) { notice('Максимальный размер аудио — 20 МБ.'); return; }
  stop(); releaseURL(); $('cues').value = '';
  objectURL = URL.createObjectURL(file); loadAudio(objectURL, [], 'amplitude');
};
$('cues').onchange = async () => {
  const file = $('cues').files[0]; if (!file) return;
  if (file.size > 5 * 1024 * 1024) { notice('JSON должен быть не больше 5 МБ.'); return; }
  try {
    const next = validateCues(JSON.parse(await file.text()));
    cues = next; cueMode = 'visemes'; notice(`Загружено ${cues.length} visemes; таймер — позиция аудиоплеера.`);
  } catch (error) { notice(error.message); }
};

let pointerX = 0, pointerY = 0;
$('stage').onpointermove = e => {
  const rect = $('stage').getBoundingClientRect();
  pointerX = (e.clientX - rect.left) / rect.width * 2 - 1;
  pointerY = (e.clientY - rect.top) / rect.height * 2 - 1;
};
$('stage').onpointerleave = () => { pointerX = pointerY = 0; };
function frame(ms) {
  const t = ms / 1000, dt = Math.min(.05, Math.max(0, t - previousTime)); previousTime = t;
  const smooth = 1 - Math.exp(-dt * 10), motion = $('motion').checked;
  if (manualUntil && ms > manualUntil) { manualUntil = 0; state.setActivity(args.state || 'idle'); }
  if (t > gazeAt) { gx = (Math.random() - .5) * 4; gy = (Math.random() - .5) * 2; gazeAt = t + 1.5 + Math.random() * 3; }
  if (t > blinkAt) { blinkStart = t; blinkAt = t + 2.4 + Math.random() * 3.8; }
  const blink = 1 - .97 * Math.max(0, Math.sin(Math.min(1, (t - blinkStart) / .17) * Math.PI));
  const mood = state.value;
  yaw += ((+$('yaw').value * 22 + (motion ? Math.sin(t * .43) * 6 + pointerX * 7 : 0)) - yaw) * smooth;
  pitch += ((+$('pitch').value * 12 + (motion ? Math.sin(t * .61) * 2 - pointerY * 3 : 0)) - pitch) * smooth;
  roll += ((+$('roll').value * 10 + (motion ? Math.sin(t * .31) * 2 + (mood === 'listening' ? -4 : 0) : 0)) - roll) * smooth;
  $('character').style.transform = `translateY(${motion ? Math.sin(t * 1.2) * 2 : 0}px) rotateX(${pitch}deg) rotateY(${yaw}deg) rotateZ(${roll}deg)`;
  for (const layer of layers) {
    const depth = +layer.dataset.depth;
    layer.setAttribute('transform', `translate(${yaw * depth / 65} ${-pitch * depth / 65})`);
  }
  for (const eye of eyes) eye.style.transform = `scaleY(${blink})`;
  for (const pupil of pupils) pupil.setAttribute('transform', `translate(${motion ? gx + pointerX * 2 + (mood === 'thinking' ? 2 : 0) : 0} ${motion ? gy + pointerY * 1.5 : 0})`);
  let target = shapes.X;
  if ($('shape').value !== 'auto') target = shapes[$('shape').value];
  else if (state.audioPlaying) {
    if (utterance) target = shapes[cueAt(ttsCues, t - ttsOrigin)];
    else if (cueMode === 'visemes') target = shapes[cueAt(cues, audio.currentTime)];
    else if (analyser) {
      analyser.getByteTimeDomainData(samples);
      let sum = 0; for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
      const level = Math.max(0, Math.min(1, (Math.sqrt(sum / samples.length) - .012) * 9));
      target = [24 + level * 3, 2 + level * 23, .6 * level, .5 * level];
    }
  }
  const blend = 1 - Math.exp(-dt * 24);
  mouth = mouth.map((v, i) => v + (target[i] - v) * blend);
  $('mouthMask').setAttribute('rx', mouth[0]); $('mouthMask').setAttribute('ry', mouth[1]);
  $('lip').setAttribute('rx', mouth[0] + 2.5); $('lip').setAttribute('ry', mouth[1] + 2.5);
  $('teeth').setAttribute('y', -mouth[1] - 12); $('teeth').style.opacity = mouth[2];
  $('tongue').setAttribute('cy', mouth[1] * .85); $('tongue').style.opacity = mouth[3];
  $('smile').style.opacity = Math.max(0, 1 - mouth[1] / 5);
  if (lastState !== mood) { lastState = mood; $('state').textContent = `● ${mood}`; $('stage').dataset.state = mood; }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// Stable key keeps this component mounted. Repeated render events never replay a reply.
window.addEventListener('message', e => {
  if (e.source !== window.parent || e.data?.type !== 'streamlit:render') return;
  args = e.data.args || {};
  if (resetId !== null && resetId !== args.reset_id) {
    stop(); releaseURL(); audio.removeAttribute('src'); audio.load();
    cues = []; lastAudioId = null; lastReplyId = null;
  }
  resetId = args.reset_id;
  state.setActivity(['idle', 'listening', 'thinking'].includes(args.state) ? args.state : 'idle');
  $('reply').disabled = !args.reply;
  if (args.audio && args.audio.id !== lastAudioId) {
    stop(); releaseURL(); lastAudioId = args.audio.id;
    loadAudio(args.audio.src, args.audio.cues, args.audio.mode);
    document.querySelector('details').open = true;
  }
  if (args.reply_id && args.reply_id !== lastReplyId) {
    lastReplyId = args.reply_id; $('text').value = args.reply || '';
    if ($('autoplay').checked && args.reply) speak(args.reply, args.language);
  }
  resize();
});
// Adapter seam for a future TTS stream: complete encoded chunks + local cue times.
// Must be called in this frame. Tokens ending never stop queued audio.
window.avatar = {
  setActivity: value => state.setActivity(value),
  generationEnded: () => state.generationEnded(),
  enqueueAudio: chunk => {
    if (!chunk || typeof chunk.src !== 'string' || !/^(blob:|data:audio\/)/.test(chunk.src)) throw Error('Expected local audio URL');
    const item = {src: chunk.src, cues: validateCues(chunk.cues)};
    if (queue.length >= 64) throw Error('Audio queue full: apply provider backpressure');
    if (utterance || pendingSpeech) stop();
    queue.push(item); if (!queueActive) { audio.pause(); playNext(); }
  }, stop, speak,
  getState: () => state.value
};
window.addEventListener('pagehide', () => { stop(); releaseURL(); context?.close(); });
send('streamlit:componentReady', {apiVersion: 1}); resize();
