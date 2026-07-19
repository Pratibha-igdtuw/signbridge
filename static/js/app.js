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
