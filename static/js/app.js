/* ===================== SignBridge frontend logic ===================== */

let GESTURES = {}; // loaded from backend: { KEY: {word, emoji} }
let activeConversationId = null;

const legendEl = document.getElementById('legend');
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

/* ---------- Load gesture vocabulary from backend ---------- */
async function loadGestureVocabulary(){
  try{
    const res = await fetch('/api/gestures');
    const list = await res.json();
    GESTURES = {};
    legendEl.innerHTML = '';
    list.forEach(g => {
      GESTURES[g.gesture_key] = { word: g.word, emoji: g.emoji };
      const span = document.createElement('span');
      span.textContent = `${g.emoji} ${g.word}`;
      legendEl.appendChild(span);
    });
  }catch(e){
    console.warn('Could not load gesture vocabulary', e);
  }
}
loadGestureVocabulary();

/* ---------- Persist a translation to the backend ---------- */
async function logTranslation(source, text, gestureKey){
  try{
    const res = await fetch('/api/translate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        source, text, gesture_key: gestureKey || null,
        conversation_id: activeConversationId
      })
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

/* ===================== Feature 1: Hand sign recognition ===================== */

function classifyGesture(lm){
  const wrist = lm[0];
  function dist(a,b){ return Math.hypot(a.x-b.x, a.y-b.y); }

  const fingers = {
    thumb:  { tip: lm[4],  pip: lm[3],  mcp: lm[2] },
    index:  { tip: lm[8],  pip: lm[6] },
    middle: { tip: lm[12], pip: lm[10] },
    ring:   { tip: lm[16], pip: lm[14] },
    pinky:  { tip: lm[20], pip: lm[18] },
  };

  const extended = {};
  for(const name of ['index','middle','ring','pinky']){
    const f = fingers[name];
    extended[name] = dist(f.tip, wrist) > dist(f.pip, wrist) * 1.15;
  }
  const thumbExtended = dist(fingers.thumb.tip, lm[17]) > dist(fingers.thumb.mcp, lm[17]) * 1.1;
  extended.thumb = thumbExtended;

  const count = Object.values(extended).filter(Boolean).length;

  if(extended.thumb && extended.index && !extended.middle && !extended.ring && extended.pinky) return 'ILY';
  if(count >= 4) return 'OPEN_HAND';
  if(count === 0) return 'FIST';
  if(extended.index && extended.middle && !extended.ring && !extended.pinky) return 'PEACE';
  if(extended.index && !extended.middle && !extended.ring && !extended.pinky && !extended.thumb) return 'ONE';
  if(extended.thumb && !extended.index && !extended.middle && !extended.ring && !extended.pinky) return 'THUMB';
  return null;
}

function onResults(results){
  overlay.width = video.videoWidth || 640;
  overlay.height = video.videoHeight || 480;
  ctx.save();
  ctx.clearRect(0,0,overlay.width, overlay.height);

  if(results.multiHandLandmarks && results.multiHandLandmarks.length > 0){
    const lm = results.multiHandLandmarks[0];

    if(window.drawConnectors){
      drawConnectors(ctx, lm, Hands.HAND_CONNECTIONS, {color:'#3FD9C7', lineWidth:3});
      drawLandmarks(ctx, lm, {color:'#F2A33E', lineWidth:1, radius:3});
    }

    const g = classifyGesture(lm);
    if(g && g === stableGesture){ stableCount++; }
    else { stableGesture = g; stableCount = 0; }

    if(g && stableCount === 6 && GESTURES[g]){
      const info = GESTURES[g];
      gestureLabelEl.textContent = `${info.emoji} ${info.word}`;
      if(lastSpokenGesture !== g){
        speak(info.word);
        addTranscriptLine('Sign', info.word, 'them');
        flashNode(nodeHearing);
        logTranslation('sign', info.word, g);
        lastSpokenGesture = g;
      }
    }
    if(!g){ gestureLabelEl.textContent = '—'; lastSpokenGesture = null; }
  } else {
    gestureLabelEl.textContent = '—';
    lastSpokenGesture = null;
  }
  ctx.restore();
}

hands = new Hands({locateFile:(f)=>`https://cdn.jsdelivr.net/npm/@mediapipe/hands/${f}`});
hands.setOptions({ maxNumHands:1, modelComplexity:1, minDetectionConfidence:0.6, minTrackingConfidence:0.6 });
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

/* ===================== Feature 5: Type -> Sign avatar preview ===================== */

const FINGERSPELL = {
  A:'🅰️', B:'🅱️', C:'🇨', D:'🇩', E:'🇪', F:'🇫', G:'🇬', H:'🇭', I:'ℹ️', J:'🇯',
  K:'🇰', L:'🇱', M:'Ⓜ️', N:'🇳', O:'🅾️', P:'🅿️', Q:'🇶', R:'🇷', S:'🇸', T:'🇹',
  U:'🇺', V:'🇻', W:'🇼', X:'🇽', Y:'🇾', Z:'🇿',
  0:'0️⃣',1:'1️⃣',2:'2️⃣',3:'3️⃣',4:'4️⃣',5:'5️⃣',6:'6️⃣',7:'7️⃣',8:'8️⃣',9:'9️⃣'
};

const avatarInput = document.getElementById('avatarInput');
const avatarPlayBtn = document.getElementById('avatarPlayBtn');
const avatarClearBtn = document.getElementById('avatarClearBtn');
const avatarStage = document.getElementById('avatarStage');

function wordToVocabMatch(word){
  const clean = word.toLowerCase().replace(/[^a-z0-9']/g, '');
  for(const key in GESTURES){
    if(GESTURES[key].word.toLowerCase() === clean) return GESTURES[key];
  }
  return null;
}

/* ---------- Signing avatar: hand-shape data (stylised, illustrative) ---------- */
// finger order: [thumb, index, middle, ring, pinky] — 0 curled, 1 half, 2 extended
const LETTER_POSES = {
  A:[2,0,0,0,0], B:[0,2,2,2,2], C:[1,1,1,1,1], D:[1,2,0,0,0], E:[0,0,0,0,0],
  F:[1,0,2,2,2], G:[2,2,0,0,0], H:[0,2,2,0,0], I:[0,0,0,0,2], J:[0,0,0,0,2],
  K:[1,2,2,0,0], L:[2,2,0,0,0], M:[0,1,1,1,0], N:[0,1,1,0,0], O:[1,1,1,1,1],
  P:[1,2,2,0,0], Q:[2,2,0,0,0], R:[0,2,2,0,0], S:[1,0,0,0,0], T:[1,0,0,0,0],
  U:[0,2,2,0,0], V:[0,2,2,0,0], W:[0,2,2,2,0], X:[0,1,0,0,0], Y:[2,0,0,0,2], Z:[0,2,0,0,0],
  0:[1,1,1,1,1], 1:[0,2,0,0,0], 2:[0,2,2,0,0], 3:[2,2,2,0,0], 4:[0,2,2,2,2],
  5:[2,2,2,2,2], 6:[2,0,2,2,2], 7:[2,2,0,2,2], 8:[2,2,2,0,2], 9:[2,2,2,2,0]
};
const WORD_POSES = {
  // iconic / closer-to-real signs
  'hello':[0,2,2,2,2], 'hi':[0,2,2,2,2], 'thank you':[0,2,2,2,2], 'please':[0,2,2,2,2],
  'good':[0,2,2,2,2], 'bad':[0,2,2,2,2], 'bye':[0,2,2,2,2], 'goodbye':[0,2,2,2,2],
  'yes':[1,0,0,0,0], 'sorry':[1,0,0,0,0],
  'i':[0,2,0,0,0], 'me':[0,2,0,0,0], 'you':[0,2,0,0,0],
  'no':[1,2,2,0,0], 'need':[0,1,0,0,0], 'friend':[0,1,0,0,0],
  'want':[1,1,1,1,1], 'eat':[1,1,1,1,1], 'more':[1,1,1,1,1],
  'water':[0,2,2,2,0], 'love':[2,2,0,0,2], 'i love you':[2,2,0,0,2],
  'like':[2,0,1,0,0], 'help':[0,2,2,2,2]
};
// generic fallback palette for other common words — stylised variety, not literal ASL
const POSE_PALETTE = [
  [2,0,0,0,0],[0,2,2,2,2],[1,1,1,1,1],[1,2,0,0,0],[0,0,0,0,0],
  [2,2,0,0,0],[0,2,2,0,0],[0,2,0,0,0],[2,0,0,0,2],[0,2,2,2,0]
];
const GENERIC_WORDS = ['we','us','they','he','she','it','my','your','is','are','am','do','does',
  'can','will','would','should','have','has','go','come','stop','wait','drink','food','home','work',
  'school','family','mother','father','sister','brother','today','tomorrow','yesterday','now','later',
  'time','day','night','morning','again','understand','know','learn','teach','read','write','talk',
  'speak','hear','see','look','feel','think','remember','forget','open','close','give','take','big',
  'small','hot','cold','fast','slow','right','wrong','happy','sad','name','what','where','when','who','why','how'];
GENERIC_WORDS.forEach(w=>{
  let sum = 0;
  for(let i=0;i<w.length;i++) sum += w.charCodeAt(i);
  WORD_POSES[w] = POSE_PALETTE[sum % POSE_PALETTE.length];
});
const RELAXED_POSE = [1,1,1,1,1];

const FINGER_DEFS = {
  fThumb:  {x:-19, y:10, angle:200, lens:[6,16,28]},
  fIndex:  {x:-9,  y:-8, angle:260, lens:[8,18,32]},
  fMiddle: {x:-2,  y:-8, angle:270, lens:[8,18,34]},
  fRing:   {x:6,   y:-8, angle:280, lens:[8,18,32]},
  fPinky:  {x:14,  y:-8, angle:290, lens:[8,16,28]}
};
const FINGER_ORDER = ['fThumb','fIndex','fMiddle','fRing','fPinky'];

// current animated length per finger, so we can glide smoothly between poses
const currentFingerLens = { fThumb:8, fIndex:8, fMiddle:8, fRing:8, fPinky:8 };
let avatarAnimId = 0;

function drawFingerAt(id, len){
  const def = FINGER_DEFS[id];
  const rad = def.angle * Math.PI / 180;
  const x2 = def.x + len * Math.cos(rad);
  const y2 = def.y + len * Math.sin(rad);
  const el = document.getElementById(id);
  if(!el) return;
  el.setAttribute('x1', def.x); el.setAttribute('y1', def.y);
  el.setAttribute('x2', x2); el.setAttribute('y2', y2);
}

function renderAvatarHand(pose){
  const myAnim = ++avatarAnimId;
  const startLens = { ...currentFingerLens };
  const targetLens = {};
  FINGER_ORDER.forEach((id, i)=>{
    targetLens[id] = FINGER_DEFS[id].lens[pose[i]];
  });
  const duration = 260; // ms — glide between hand-shapes instead of snapping
  const t0 = performance.now();
  function step(now){
    if(myAnim !== avatarAnimId) return; // a newer pose took over, stop this one
    const raw = Math.min(1, (now - t0) / duration);
    const eased = 1 - Math.pow(1 - raw, 2); // ease-out
    FINGER_ORDER.forEach(id=>{
      const len = startLens[id] + (targetLens[id] - startLens[id]) * eased;
      currentFingerLens[id] = len;
      drawFingerAt(id, len);
    });
    if(raw < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

let avatarTimers = [];
function clearAvatarTimers(){ avatarTimers.forEach(t=>clearTimeout(t)); avatarTimers = []; }

/* ---------- Sign-language dropdown (ASL live, others coming soon) ---------- */
const langPickerBtn = document.getElementById('langPickerBtn');
const langPickerPanel = document.getElementById('langPickerPanel');
const langPickerLabel = document.getElementById('langPickerLabel');
const langToast = document.getElementById('langToast');
let langToastTimer = null;

if(langPickerBtn && langPickerPanel){
  langPickerBtn.addEventListener('click', (e)=>{
    e.stopPropagation();
    langPickerPanel.hidden = !langPickerPanel.hidden;
  });
  document.addEventListener('click', (e)=>{
    if(!langPickerPanel.hidden && !langPickerPanel.contains(e.target) && e.target !== langPickerBtn){
      langPickerPanel.hidden = true;
    }
  });
  langPickerPanel.querySelectorAll('.lang-option').forEach(opt=>{
    opt.addEventListener('click', ()=>{
      langPickerPanel.hidden = true;
      if(opt.dataset.lang === 'ASL'){
        langPickerPanel.querySelectorAll('.lang-option').forEach(o=>o.classList.remove('active'));
        opt.classList.add('active');
        langPickerLabel.textContent = opt.dataset.name;
        return;
      }
      if(langToast){
        langToast.textContent = `${opt.dataset.name} support is coming soon — showing American Sign Language for now.`;
        langToast.hidden = false;
        clearTimeout(langToastTimer);
        langToastTimer = setTimeout(()=>{ langToast.hidden = true; }, 2600);
      }
    });
  });
}

/* ---------- Avatar style picker ---------- */
const avatarSvg = document.getElementById('avatarSvg');
const avatarCaption = document.getElementById('avatarCaption');
const stylePicker = document.getElementById('avatarStylePicker');
const THEMES = ['warm','midnight','ocean','ember'];

function applyAvatarTheme(theme){
  if(!avatarSvg) return;
  THEMES.forEach(t => avatarSvg.classList.remove(`avatar-theme-${t}`));
  avatarSvg.classList.add(`avatar-theme-${theme}`);
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
if(avatarSvg) renderAvatarHand(RELAXED_POSE);

function buildAvatarTiles(text){
  avatarStage.innerHTML = '';
  clearAvatarTimers();
  const words = text.trim().split(/\s+/).filter(Boolean);
  if(!words.length){
    avatarStage.innerHTML = '<div class="avatar-tile empty" id="avatarPlaceholder">Sign preview will play here…</div>';
    if(avatarCaption) avatarCaption.textContent = 'Sign preview will play here…';
    renderAvatarHand(RELAXED_POSE);
    return;
  }
  let delay = 0;
  const fullClean = words.join(' ').toLowerCase().replace(/[^a-z0-9' ]/g, '').trim();
  if(WORD_POSES[fullClean]){
    // whole phrase matches a known sign (e.g. "thank you", "i love you")
    const tile = document.createElement('div');
    tile.className = 'avatar-tile';
    tile.style.animationDelay = '0ms';
    tile.innerHTML = `<div class="glyph">🤟</div><div class="cap">${text}</div>`;
    avatarStage.appendChild(tile);
    avatarTimers.push(setTimeout(()=>{
      renderAvatarHand(WORD_POSES[fullClean]);
      if(avatarCaption) avatarCaption.textContent = text;
    }, 0));
    delay = 900;
  } else {
    words.forEach(word=>{
      const match = wordToVocabMatch(word);
      const cleanWord = word.toLowerCase().replace(/[^a-z0-9']/g, '');
      if(match || WORD_POSES[cleanWord]){
        const tile = document.createElement('div');
        tile.className = 'avatar-tile';
        tile.style.animationDelay = `${delay}ms`;
        const label = match ? match.word : word;
        const glyph = match ? match.emoji : '🤟';
        tile.innerHTML = `<div class="glyph">${glyph}</div><div class="cap">${label}</div>`;
        avatarStage.appendChild(tile);
        const pose = WORD_POSES[cleanWord] || RELAXED_POSE;
        const stepDelay = delay;
        avatarTimers.push(setTimeout(()=>{
          renderAvatarHand(pose);
          if(avatarCaption) avatarCaption.textContent = label;
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
          tile.innerHTML = `<div class="glyph">${ch.toUpperCase()}</div><div class="cap">fingerspell</div>`;
          avatarStage.appendChild(tile);
          const pose = LETTER_POSES[ch.toUpperCase()] || RELAXED_POSE;
          const stepDelay = delay;
          avatarTimers.push(setTimeout(()=>{
            renderAvatarHand(pose);
            if(avatarCaption) avatarCaption.textContent = ch.toUpperCase();
          }, stepDelay));
          delay += 450;
        });
      }
    });
  }
  avatarTimers.push(setTimeout(()=>{
    renderAvatarHand(RELAXED_POSE);
    if(avatarCaption) avatarCaption.textContent = text;
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
    renderAvatarHand(RELAXED_POSE);
    if(avatarCaption) avatarCaption.textContent = 'Sign preview will play here…';
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
