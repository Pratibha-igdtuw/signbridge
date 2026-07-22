/* ===================== SignBridge frontend logic ===================== */

let GESTURES = {};       // gesture_key -> {word, emoji} for the currently loaded language (all, incl. reference-only)
let SHAPE_MAP = {};      // shape_key -> {gesture_key, word, emoji} — only the camera-detectable ones
let currentLanguage = 'ASL';
let activeConversationId = null;

const legendEl = document.getElementById('legend');
const legendLangLabelEl = document.getElementById('legendLangLabel');
const camLangSeg = document.getElementById('camLangSeg');
const video = document.getElementById('video');
const overlay = document.getElementById('overlay');
const ctx = overlay.getContext('2d');
const camOff = document.getElementById('camOff');
const gestureLabelEl = document.getElementById('gestureLabel');
const nodeDeaf = document.getElementById('nodeDeaf');
const nodeHearing = document.getElementById('nodeHearing');
const transcriptEl = document.getElementById('transcript');
const micBtn = document.getElementById('micBtn');

let speakEnabled = true;
let lastSpokenGesture = null;
let stableGesture = null;
let stableCount = 0;
let camera = null;
let hands = null;

/* ---------- Load gesture vocabulary from backend for a given language ---------- */
async function loadGestureVocabulary(language){
  currentLanguage = language || currentLanguage;
  try{
    const res = await fetch(`/api/gestures?language=${encodeURIComponent(currentLanguage)}`);
    const list = await res.json();
    GESTURES = {};
    SHAPE_MAP = {};

    const detectableOpts = [];
    const referenceOpts = [];

    list.forEach(g => {
      GESTURES[g.gesture_key] = { word: g.word, emoji: g.emoji };
      if(g.detectable && g.shape_key){
        SHAPE_MAP[g.shape_key] = { gesture_key: g.gesture_key, word: g.word, emoji: g.emoji };
        detectableOpts.push(g);
      } else {
        referenceOpts.push(g);
      }
    });

    legendEl.innerHTML = '';
    if(detectableOpts.length){
      const grp = document.createElement('optgroup');
      grp.label = '🎥 Live camera detection';
      detectableOpts.forEach(g => {
        const opt = document.createElement('option');
        opt.textContent = `${g.emoji} ${g.word}`;
        grp.appendChild(opt);
      });
      legendEl.appendChild(grp);
    }
    if(referenceOpts.length){
      const grp = document.createElement('optgroup');
      grp.label = '📖 Full vocabulary (reference)';
      referenceOpts.forEach(g => {
        const opt = document.createElement('option');
        opt.textContent = `${g.emoji} ${g.word}`;
        grp.appendChild(opt);
      });
      legendEl.appendChild(grp);
    }
    if(legendLangLabelEl) legendLangLabelEl.textContent = `· ${currentLanguage} (${list.length} signs)`;

    // reset live-tracking state so a stale shape from the old language doesn't fire
    stableGesture = null;
    stableCount = 0;
    lastSpokenGesture = null;
    if(gestureLabelEl) gestureLabelEl.textContent = '—';
  }catch(e){
    console.warn('Could not load gesture vocabulary', e);
  }
}
loadGestureVocabulary(currentLanguage);

if(camLangSeg){
  camLangSeg.addEventListener('click', (e)=>{
    const btn = e.target.closest('.lang-seg-btn');
    if(!btn) return;
    camLangSeg.querySelectorAll('.lang-seg-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    resetIslCapture();
    loadGestureVocabulary(btn.dataset.lang);
  });
}

/* ---------- Persist a translation to the backend (offline-queued if needed) ---------- */
async function logTranslation(source, text, gestureKey){
  const payload = { source, text, gesture_key: gestureKey || null, conversation_id: activeConversationId };
  try{
    if(window.SignBridgeOffline){
      const result = await window.SignBridgeOffline.queueOrSend('translation', '/api/translate', payload);
      if(!result.queued && result.response && !activeConversationId){
        activeConversationId = result.response.conversation_id;
      }
      return;
    }
    const res = await fetch('/api/translate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if(res.ok && !activeConversationId){
      activeConversationId = data.conversation_id;
    }
  }catch(e){
    console.warn('Could not log translation (backend unreachable)', e);
  }
}

function speak(text){
  if(!speakEnabled) return;
  try{
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 0.95;
    speechSynthesis.cancel();
    speechSynthesis.speak(utt);
  }catch(e){ console.warn('TTS unavailable', e); }
}

function flashNode(node){
  node.classList.add('active');
  setTimeout(()=>node.classList.remove('active'), 700);
}

function addTranscriptLine(who, text, cls){
  if(transcriptEl.querySelector('.empty')) transcriptEl.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'line';
  div.innerHTML = `<span class="who ${cls==='you'?'you':''}">${who}:</span>${text}`;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

/* ===================== AI Sentence Prediction & Auto-Completion ===================== */

let gestureHistory = [];
const gestureSuggestionsEl = document.getElementById('gestureSuggestions');
const replySuggestionsEl = document.getElementById('replySuggestions');

function renderChips(container, suggestions, onPick){
  if(!container) return;
  container.innerHTML = '';
  suggestions.forEach((s, i) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'suggestion-chip';
    chip.style.animationDelay = `${i * 40}ms`;
    chip.innerHTML = `${s.text}<span class="conf">${s.confidence}%</span>`;
    chip.addEventListener('click', () => { onPick(s.text); container.innerHTML = ''; });
    container.appendChild(chip);
  });
}

async function fetchGestureSuggestions(){
  if(!navigator.onLine){ gestureSuggestionsEl.innerHTML = ''; return; } // predictions need the server; skip quietly offline
  try{
    const res = await fetch('/api/predict/gesture', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ history: gestureHistory, conversation_id: activeConversationId }),
    });
    const data = await res.json();
    renderChips(gestureSuggestionsEl, data.suggestions || [], (text) => {
      addTranscriptLine('Sign', text, 'them');
      flashNode(nodeHearing);
      speak(text);
      logTranslation('sign', text, null);
      gestureHistory = [];
    });
  }catch(e){ /* non-fatal — suggestions are a nice-to-have, not required for core translation */ }
}

async function fetchReplySuggestions(transcript){
  if(!navigator.onLine){ replySuggestionsEl.innerHTML = ''; return; }
  try{
    const res = await fetch('/api/predict/reply', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ transcript, conversation_id: activeConversationId }),
    });
    const data = await res.json();
    renderChips(replySuggestionsEl, data.suggestions || [], (text) => {
      addTranscriptLine('Sign', text, 'them');
      flashNode(nodeHearing);
      speak(text);
      logTranslation('sign', text, null);
    });
  }catch(e){ /* non-fatal */ }
}

/* ===================== Feature 1: Hand sign recognition ===================== */

// Every possible sign is reduced to which of the 5 fingers are extended.
// This table is what actually determines what the camera CAN tell apart —
// 11 distinguishable static hand shapes, shared across all 3 languages.
// ASL numbers verified against "American Sign Language For Dummies" (Penilla &
// Taylor): 3 is thumb+index+middle (not just index+middle+ring — that shape is
// actually 6, distinguished from 3 by the thumb), and 6-9 are the "3/4-fingers up,
// thumb touches one fingertip" family — which finger the thumb touches is what
// tells them apart, so each gets its own key here.
const SHAPE_TABLE = {
  '00000': 'FIST',
  '11111': 'OPEN_HAND',
  '01000': 'ONE',
  '01100': 'TWO',
  '11100': 'THREE',   // thumb + index + middle
  '01111': 'FOUR',
  '01110': 'SIX',      // index+middle+ring up, thumb touches pinky tip
  '01101': 'SEVEN',    // index+middle+pinky up, thumb touches ring tip
  '01011': 'EIGHT',    // index+ring+pinky up, thumb touches middle tip
  '00111': 'NINE',     // middle+ring+pinky up, thumb touches index tip
  '10000': 'THUMB',
  '00001': 'PINKY',
  '11001': 'ILY',
  '01001': 'ROCK',
};

// ---------- Local geometry classifier (always available, fully offline) ----------
// Returns a confidence alongside the shape, instead of a flat yes/no: each finger's
// extended/curled reading has a margin (how far its tip/knuckle distance ratio sits
// from the 1.0 decision boundary). Averaging those margins gives a rough but honest
// 0..1 confidence — a fist held loosely reads lower than one held tight, for example.
function classifyGestureLocal(lm){
  const wrist = lm[0];
  function dist(a,b){ return Math.hypot(a.x-b.x, a.y-b.y); }

  const fingers = {
    thumb:  { tip: lm[4],  pip: lm[3],  mcp: lm[2] },
    index:  { tip: lm[8],  pip: lm[6] },
    middle: { tip: lm[12], pip: lm[10] },
    ring:   { tip: lm[16], pip: lm[14] },
    pinky:  { tip: lm[20], pip: lm[18] },
  };

  const ratios = {};
  for(const name of ['index','middle','ring','pinky']){
    const f = fingers[name];
    ratios[name] = dist(f.tip, wrist) / (dist(f.pip, wrist) * 1.15);
  }
  ratios.thumb = dist(fingers.thumb.tip, lm[17]) / (dist(fingers.thumb.mcp, lm[17]) * 1.1);

  const key = ['thumb','index','middle','ring','pinky']
    .map(name => ratios[name] > 1 ? '1' : '0').join('');

  const shapeKey = SHAPE_TABLE[key] || null;
  if(!shapeKey) return { shapeKey: null, confidence: 0 };

  const margins = Object.values(ratios).map(r => Math.min(Math.abs(r - 1) / 0.6, 1));
  const confidence = margins.reduce((a,b) => a+b, 0) / margins.length;

  return { shapeKey, confidence };
}

// ---------- Optional external ML classifier (plug-in point) ----------
// Leave ML_API_URL empty (default) to run entirely on the local geometry classifier
// above — no extra hosting needed, works fine on a free PythonAnywhere tier.
// To upgrade later to a real trained model (e.g. a Random Forest/CNN over hand
// landmarks, served from a small standalone FastAPI/Flask microservice hosted
// elsewhere — same idea as SignBridgeV2's separate ML API), just set ML_API_URL
// below. It must accept POST { landmarks: [{x,y,z}, ...] } (21 MediaPipe hand
// landmarks) and respond with { sign: "<SHAPE_TABLE key>", confidence: 0..1 }.
// Everything else — stability tracking, speak-once logic, transcript, suggestions —
// keeps working unchanged, because both paths return the same {shapeKey, confidence} shape.
const ML_API_URL = '';
const ML_CONFIDENCE_THRESHOLD = 0.6;
const ML_DEBOUNCE_MS = 300;

let mlFetchInFlight = false;
let lastMlFetchAt = 0;
let mlApiHealthy = !!ML_API_URL;

async function classifyGestureRemote(lm){
  if(!ML_API_URL || !mlApiHealthy) return null;
  const now = Date.now();
  if(mlFetchInFlight || now - lastMlFetchAt < ML_DEBOUNCE_MS) return null;
  mlFetchInFlight = true;
  lastMlFetchAt = now;
  try{
    const res = await fetch(ML_API_URL, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ landmarks: lm.map(({x,y,z}) => ({x,y,z})) }),
    });
    if(!res.ok) throw new Error(`ML API returned ${res.status}`);
    const data = await res.json();
    if(typeof data.confidence !== 'number' || !data.sign) return null;
    if(data.confidence < ML_CONFIDENCE_THRESHOLD) return { shapeKey: null, confidence: data.confidence };
    return { shapeKey: data.sign, confidence: data.confidence };
  }catch(e){
    // Don't take down sign recognition just because the ML microservice is
    // unreachable/misconfigured — fall back to the local classifier for the
    // rest of the session and let the console explain why.
    mlApiHealthy = false;
    console.warn('ML classifier unavailable, falling back to local geometry classifier:', e.message);
    return null;
  }finally{
    mlFetchInFlight = false;
  }
}

async function classifySign(lm){
  const remote = await classifyGestureRemote(lm);
  return remote || classifyGestureLocal(lm);
}

// ---------- Live confidence readout ----------
// Injected next to the existing "Detected Sign" value so no template changes
// are needed. Shows live confidence plus how close the hold is to locking in.
let confidenceEl = document.getElementById('gestureConfidence');
if(!confidenceEl && gestureLabelEl){
  confidenceEl = document.createElement('div');
  confidenceEl.id = 'gestureConfidence';
  confidenceEl.className = 'label';
  confidenceEl.style.cssText = 'margin-top:2px;font-size:0.8em;opacity:0.7;';
  gestureLabelEl.insertAdjacentElement('afterend', confidenceEl);
}

const STABLE_FRAMES_REQUIRED = 6;

function updateConfidenceReadout(shapeKey, confidence){
  if(!confidenceEl) return;
  if(!shapeKey){ confidenceEl.textContent = ''; return; }
  const pct = Math.round((confidence || 0) * 100);
  const holding = stableCount < STABLE_FRAMES_REQUIRED ? ` · holding ${stableCount}/${STABLE_FRAMES_REQUIRED}` : '';
  confidenceEl.textContent = `${pct}% confidence${holding}`;
}

function handleClassification(shapeKey, confidence){
  if(shapeKey && shapeKey === stableGesture){ stableCount++; }
  else { stableGesture = shapeKey; stableCount = 0; }

  updateConfidenceReadout(shapeKey, confidence);

  // Debug aid: open the browser console (F12) while signing to see exactly what
  // raw shape key the classifier read each frame, and whether it's wired to a word
  // in SHAPE_MAP yet. Cheap no-op in normal use.
  if(shapeKey && stableCount === STABLE_FRAMES_REQUIRED && !SHAPE_MAP[shapeKey]){
    console.debug(`SignBridge: recognized shape "${shapeKey}" but it isn't wired to any word in ${currentLanguage} yet.`);
  }

  if(shapeKey && stableCount === STABLE_FRAMES_REQUIRED && SHAPE_MAP[shapeKey]){
    const info = SHAPE_MAP[shapeKey];
    gestureLabelEl.textContent = `${info.emoji} ${info.word}`;
    if(lastSpokenGesture !== shapeKey){
      speak(info.word);
      addTranscriptLine('Sign', info.word, 'them');
      flashNode(nodeHearing);
      logTranslation('sign', info.word, info.gesture_key);
      lastSpokenGesture = shapeKey;
      gestureHistory.push(info.word);
      if(gestureHistory.length > 5) gestureHistory.shift();
      fetchGestureSuggestions();
    }
  }
  if(!shapeKey){ gestureLabelEl.textContent = '—'; lastSpokenGesture = null; }
}

// ---------- ISL word-level detection (external model, quick demo) ----------
// When the selected language is ISL, we skip the static shape classifier and
// instead recognize real ISL *words* (not just hand shapes) by streaming short
// clips of raw camera frames to a hosted model — see isl_predict_routes.py for
// full details and caveats. This is a demo integration: it depends on a
// third-party's free Hugging Face Space, so treat it as "nice when it works",
// not a guaranteed always-on feature. Everything below only ever runs when
// currentLanguage === 'ISL'; ASL/BSL keep using the fast, fully-offline
// geometry classifier above, unaffected.
const ISL_CLIP_LENGTH = 16;
const ISL_FRAME_INTERVAL_MS = 80; // ~12.5 fps — matches the reference model's training/serving setup
const ISL_RESIZE_DIM = 224;       // the model expects 224x224 frames

let islFrameBuffer = [];
let islLastCaptureAt = 0;
let islRequestInFlight = false;
let islCaptureCanvas = null;

function resetIslCapture(){
  islFrameBuffer = [];
  islLastCaptureAt = 0;
  islRequestInFlight = false;
}

function captureIslFrame(){
  if(!islCaptureCanvas){
    islCaptureCanvas = document.createElement('canvas');
    islCaptureCanvas.width = ISL_RESIZE_DIM;
    islCaptureCanvas.height = ISL_RESIZE_DIM;
  }
  islCaptureCanvas.getContext('2d').drawImage(video, 0, 0, ISL_RESIZE_DIM, ISL_RESIZE_DIM);
  // quality 0.8 keeps payload size reasonable without visibly hurting recognition
  return islCaptureCanvas.toDataURL('image/jpeg', 0.8).split(',')[1];
}

async function submitIslClip(frames){
  islRequestInFlight = true;
  if(confidenceEl) confidenceEl.textContent = 'Recognizing…';
  try{
    const res = await fetch('/api/isl/predict/frames', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ frames }),
    });
    const data = await res.json();

    if(!res.ok || data.error){
      if(confidenceEl) confidenceEl.textContent = 'ISL model unavailable right now — try again shortly.';
      return;
    }

    const word = data.prediction;
    const conf = typeof data.confidence === 'number' ? data.confidence : 0;
    if(!word) return;

    gestureLabelEl.textContent = `🤟 ${word}`;
    if(confidenceEl) confidenceEl.textContent = `${Math.round(conf*100)}% confidence (ISL word model)`;

    if(lastSpokenGesture !== word){
      speak(word);
      addTranscriptLine('Sign', word, 'them');
      flashNode(nodeHearing);
      logTranslation('sign', word, null);
      lastSpokenGesture = word;
      gestureHistory.push(word);
      if(gestureHistory.length > 5) gestureHistory.shift();
      fetchGestureSuggestions();
    }
  }catch(e){
    if(confidenceEl) confidenceEl.textContent = 'ISL model unreachable — check your connection.';
  }finally{
    islRequestInFlight = false;
  }
}

function handleIslFrame(){
  const now = Date.now();
  if(now - islLastCaptureAt < ISL_FRAME_INTERVAL_MS) return;
  islLastCaptureAt = now;

  islFrameBuffer.push(captureIslFrame());
  if(islFrameBuffer.length >= ISL_CLIP_LENGTH && !islRequestInFlight){
    const clip = islFrameBuffer.slice(0, ISL_CLIP_LENGTH);
    islFrameBuffer = [];
    submitIslClip(clip);
  }
}

// Classify every visible hand and keep whichever reading is currently strongest.
// Most signs in this project's vocabulary are single-handed (numbers, letters,
// ILY, etc.), so a second hand in frame — a support hand, or just a hand resting
// in view — shouldn't block detection. This also means signers who favor either
// hand still get recognized, instead of only ever reading "hand #1".
async function classifyHands(handsLandmarksList){
  const results = await Promise.all(handsLandmarksList.map(lm => classifySign(lm)));
  let best = { shapeKey: null, confidence: 0 };
  for(const r of results){
    if(r.shapeKey && r.confidence > best.confidence) best = r;
  }
  return best;
}

function onResults(results){
  overlay.width = video.videoWidth || 640;
  overlay.height = video.videoHeight || 480;
  ctx.save();
  ctx.clearRect(0,0,overlay.width, overlay.height);

  const handsList = results.multiHandLandmarks || [];

  if(handsList.length > 0){
    if(window.drawConnectors){
      handsList.forEach(lm => {
        drawConnectors(ctx, lm, Hands.HAND_CONNECTIONS, {color:'#3FD9C7', lineWidth:3});
        drawLandmarks(ctx, lm, {color:'#F2A33E', lineWidth:1, radius:3});
      });
    }

    if(currentLanguage === 'ISL'){
      handleIslFrame();
    } else {
      classifyHands(handsList).then(({shapeKey, confidence}) => handleClassification(shapeKey, confidence));
    }
  } else if(currentLanguage !== 'ISL'){
    handleClassification(null, 0);
  }
  ctx.restore();
}

hands = new Hands({locateFile:(f)=>`https://cdn.jsdelivr.net/npm/@mediapipe/hands/${f}`});
hands.setOptions({ maxNumHands:2, modelComplexity:1, minDetectionConfidence:0.6, minTrackingConfidence:0.6 });
hands.onResults(onResults);

document.getElementById('startCam').addEventListener('click', async ()=>{
  try{
    camOff.style.display = 'none';
    camera = new Camera(video, {
      onFrame: async ()=>{ await hands.send({image: video}); },
      width:640, height:480
    });
    await camera.start();
    document.getElementById('startCam').disabled = true;
    document.getElementById('stopCam').disabled = false;
  }catch(e){
    camOff.style.display = 'flex';
    camOff.textContent = 'Camera access was blocked or unavailable in this environment. Try opening this page directly in Chrome on your own device.';
  }
});

document.getElementById('stopCam').addEventListener('click', ()=>{
  if(camera){ camera.stop(); }
  const stream = video.srcObject;
  if(stream){ stream.getTracks().forEach(t=>t.stop()); }
  camOff.style.display = 'flex';
  camOff.textContent = 'Camera stopped.';
  document.getElementById('startCam').disabled = false;
  document.getElementById('stopCam').disabled = true;
  ctx.clearRect(0,0,overlay.width, overlay.height);
  resetIslCapture();
});

document.getElementById('muteBtn').addEventListener('click', (e)=>{
  speakEnabled = !speakEnabled;
  e.target.textContent = speakEnabled ? '🔊 Speak: On' : '🔈 Speak: Off';
});

/* ===================== Feature 2: Speech -> Text ===================== */

let recognition = null;
let listening = false;

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if(SR){
  recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  recognition.onresult = (event)=>{
    const text = event.results[event.results.length-1][0].transcript;
    addTranscriptLine('Voice', text, 'you');
    flashNode(nodeDeaf);
    logTranslation('voice', text, null);
    fetchReplySuggestions(text);
  };
  recognition.onerror = ()=>{ stopListening(); };
  recognition.onend = ()=>{ if(listening){ recognition.start(); } };
} else {
  micBtn.textContent = 'Speech recognition is not supported in this browser. Try Chrome.';
  micBtn.style.cursor = 'not-allowed';
}

function startListening(){
  if(!recognition) return;
  listening = true;
  recognition.start();
  micBtn.classList.add('listening');
  micBtn.textContent = '🔴 Listening… tap to stop';
}
function stopListening(){
  listening = false;
  if(recognition) recognition.stop();
  micBtn.classList.remove('listening');
  micBtn.textContent = '🎤 Tap to start listening (hearing person speaks here)';
}
micBtn.addEventListener('click', ()=>{
  if(!recognition) return;
  listening ? stopListening() : startListening();
});

/* ===================== Feature 3: Conversation controls (backend-backed) ===================== */

document.getElementById('clearChat').addEventListener('click', async ()=>{
  transcriptEl.innerHTML = '<div class="empty">Conversation will appear here…</div>';
  const url = activeConversationId ? `/api/history?conversation_id=${activeConversationId}` : '/api/history';
  try{ await fetch(url, {method:'DELETE'}); }catch(e){}
});

document.getElementById('newConvo').addEventListener('click', async ()=>{
  try{
    const res = await fetch('/api/conversations/new', {method:'POST'});
    const data = await res.json();
    activeConversationId = data.conversation_id;
    transcriptEl.innerHTML = '<div class="empty">New conversation started…</div>';
  }catch(e){
    console.warn('Could not start a new conversation', e);
  }
});

/* ===================== Feature 4: Type-to-send + quick phrases ===================== */

const typeInput = document.getElementById('typeInput');
const typeSendBtn = document.getElementById('typeSendBtn');

function sendTypedMessage(){
  if(!typeInput) return;
  const text = typeInput.value.trim();
  if(!text) return;
  addTranscriptLine('Voice', text, 'you');
  flashNode(nodeDeaf);
  logTranslation('voice', text, null);
  fetchReplySuggestions(text);
  typeInput.value = '';
  typeInput.focus();
}

if(typeSendBtn){
  typeSendBtn.addEventListener('click', sendTypedMessage);
  typeInput.addEventListener('keydown', (e)=>{
    if(e.key === 'Enter'){ e.preventDefault(); sendTypedMessage(); }
  });
}

document.querySelectorAll('.chip[data-text]').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    if(!typeInput) return;
    typeInput.value = btn.dataset.text;
    typeInput.focus();
  });
});

/* ===================== Feature 5: Type -> Sign preview (icon-based, backend vocab) ===================== */

const FINGERSPELL = {
  A:'A', B:'B', C:'C', D:'D', E:'E', F:'F', G:'G', H:'H', I:'I', J:'J',
  K:'K', L:'L', M:'M', N:'N', O:'O', P:'P', Q:'Q', R:'R', S:'S', T:'T',
  U:'U', V:'V', W:'W', X:'X', Y:'Y', Z:'Z',
  0:'0',1:'1',2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9'
};

const avatarInput = document.getElementById('avatarInput');
const avatarPlayBtn = document.getElementById('avatarPlayBtn');
const avatarClearBtn = document.getElementById('avatarClearBtn');
const avatarStage = document.getElementById('avatarStage');
const avatarLangSeg = document.getElementById('avatarLangSeg');
const signHero = document.getElementById('signHero');
const signHeroIcon = document.getElementById('signHeroIcon');
const signHeroWord = document.getElementById('signHeroWord');
const signHeroLang = document.getElementById('signHeroLang');

// This is decoupled from the camera's language/vocabulary on purpose —
// someone can be reading BSL on camera while typing an ISL phrase to preview.
let avatarLanguage = 'ASL';
let avatarVocab = {}; // lowercased word/phrase -> {word, emoji, gesture_key}

async function loadAvatarVocab(language){
  avatarLanguage = language || avatarLanguage;
  try{
    const res = await fetch(`/api/gestures?language=${encodeURIComponent(avatarLanguage)}`);
    const list = await res.json();
    avatarVocab = {};
    list.forEach(g => { avatarVocab[g.word.toLowerCase()] = g; });
    if(signHeroLang) signHeroLang.textContent = avatarLanguage;
  }catch(e){
    console.warn('Could not load avatar vocabulary', e);
  }
}
loadAvatarVocab(avatarLanguage);

if(avatarLangSeg){
  avatarLangSeg.addEventListener('click', (e)=>{
    const btn = e.target.closest('.lang-seg-btn');
    if(!btn) return;
    avatarLangSeg.querySelectorAll('.lang-seg-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    loadAvatarVocab(btn.dataset.lang);
  });
}

function wordToVocabMatch(word){
  const clean = word.toLowerCase().replace(/[^a-z0-9' ]/g, '').trim();
  return avatarVocab[clean] || null;
}

/* ---------- Avatar theme picker (colors the sign-hero card) ---------- */
const stylePicker = document.getElementById('avatarStylePicker');
const THEMES = ['warm','midnight','ocean','ember'];

function applyAvatarTheme(theme){
  if(!signHero) return;
  THEMES.forEach(t => signHero.classList.remove(`avatar-theme-${t}`));
  signHero.classList.add(`avatar-theme-${theme}`);
  if(stylePicker){
    stylePicker.querySelectorAll('.style-swatch').forEach(btn=>{
      btn.classList.toggle('active', btn.dataset.style === theme);
    });
  }
  try{ localStorage.setItem('sb_avatar_style', theme); }catch(e){}
}

if(stylePicker){
  stylePicker.querySelectorAll('.style-swatch').forEach(btn=>{
    btn.addEventListener('click', ()=> applyAvatarTheme(btn.dataset.style));
  });
}

let savedTheme = 'ocean';
try{ savedTheme = localStorage.getItem('sb_avatar_style') || 'ocean'; }catch(e){}
applyAvatarTheme(savedTheme);

function updateSignHero(word, emoji){
  if(signHeroIcon) signHeroIcon.textContent = emoji || '🤟';
  if(signHeroWord) signHeroWord.textContent = word || 'Sign preview will play here…';
}

let avatarTimers = [];
function clearAvatarTimers(){ avatarTimers.forEach(t=>clearTimeout(t)); avatarTimers = []; }

function buildAvatarTiles(text){
  avatarStage.innerHTML = '';
  clearAvatarTimers();
  const words = text.trim().split(/\s+/).filter(Boolean);
  if(!words.length){
    avatarStage.innerHTML = '<div class="avatar-tile empty" id="avatarPlaceholder">Sign preview will play here…</div>';
    updateSignHero(null, '🤟');
    return;
  }

  let delay = 0;
  const fullPhraseMatch = wordToVocabMatch(words.join(' '));

  if(fullPhraseMatch){
    // whole phrase matches a known sign in this language's vocabulary (e.g. "thank you", "good morning")
    const tile = document.createElement('div');
    tile.className = 'avatar-tile';
    tile.style.animationDelay = '0ms';
    tile.innerHTML = `<div class="glyph">${fullPhraseMatch.emoji}</div><div class="cap">${fullPhraseMatch.word}</div>`;
    avatarStage.appendChild(tile);
    avatarTimers.push(setTimeout(()=>{
      updateSignHero(fullPhraseMatch.word, fullPhraseMatch.emoji);
    }, 0));
    delay = 900;
  } else {
    words.forEach(word=>{
      const match = wordToVocabMatch(word);
      if(match){
        const tile = document.createElement('div');
        tile.className = 'avatar-tile';
        tile.style.animationDelay = `${delay}ms`;
        tile.innerHTML = `<div class="glyph">${match.emoji}</div><div class="cap">${match.word}</div>`;
        avatarStage.appendChild(tile);
        const stepDelay = delay;
        avatarTimers.push(setTimeout(()=>{
          updateSignHero(match.word, match.emoji);
        }, stepDelay));
        delay += 750;
      } else {
        const letters = word.replace(/[^a-zA-Z0-9]/g, '').split('');
        letters.forEach(ch=>{
          const glyph = FINGERSPELL[ch.toUpperCase()];
          if(!glyph) return;
          const tile = document.createElement('div');
          tile.className = 'avatar-tile letter';
          tile.style.animationDelay = `${delay}ms`;
          tile.innerHTML = `<div class="glyph">${glyph}</div><div class="cap">fingerspell</div>`;
          avatarStage.appendChild(tile);
          const stepDelay = delay;
          avatarTimers.push(setTimeout(()=>{
            updateSignHero(ch.toUpperCase(), glyph);
          }, stepDelay));
          delay += 450;
        });
      }
    });
  }

  avatarTimers.push(setTimeout(()=>{
    updateSignHero(text, fullPhraseMatch ? fullPhraseMatch.emoji : '🤟');
  }, delay + 500));
}

if(avatarPlayBtn){
  avatarPlayBtn.addEventListener('click', ()=>{
    const text = avatarInput.value.trim();
    if(!text) return;
    buildAvatarTiles(text);
    logTranslation('text', text, null);
  });
  avatarClearBtn.addEventListener('click', ()=>{
    avatarInput.value = '';
    clearAvatarTimers();
    updateSignHero(null, '🤟');
    avatarStage.innerHTML = '<div class="avatar-tile empty" id="avatarPlaceholder">Sign preview will play here…</div>';
  });
  document.querySelectorAll('.chip[data-avatar]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      avatarInput.value = btn.dataset.avatar;
      buildAvatarTiles(btn.dataset.avatar);
      logTranslation('text', btn.dataset.avatar, null);
    });
  });
}