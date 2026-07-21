/* ===================== Live Conversation (two-way messaging screen) ===================== */

const leftList = document.getElementById('liveMessagesLeft');
const rightList = document.getElementById('liveMessagesRight');

function speak(text){
  try{
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 0.95;
    speechSynthesis.cancel();
    speechSynthesis.speak(utt);
  }catch(e){ console.warn('TTS unavailable', e); }
}

function sourceLabel(source){
  return source === 'sign' ? 'Sign' : source === 'voice' ? 'Speech' : 'Text';
}

function renderMessage(container, msg){
  if(container.querySelector('.empty')) container.innerHTML = '';
  const div = document.createElement('div');
  div.className = `live-bubble ${msg.sender}`;
  const time = new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  div.innerHTML = `<div class="text">${msg.text}</div><div class="meta"><span>${msg.sender === 'hearing' ? 'Hearing person' : 'Deaf user'}</span>·<span>${sourceLabel(msg.source)}</span>·<span>${time}</span></div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight; // auto-scroll
}

function renderAll(messages){
  leftList.innerHTML = '';
  rightList.innerHTML = '';
  if(!messages.length){
    leftList.innerHTML = '<div class="empty">Conversation will appear here…</div>';
    rightList.innerHTML = '<div class="empty">Conversation will appear here…</div>';
    return;
  }
  messages.forEach(m => { renderMessage(leftList, m); renderMessage(rightList, m); });
}

let allMessages = [];

async function loadConversation(){
  try{
    const res = await fetch('/api/live/conversation');
    const data = await res.json();
    allMessages = data.messages;
    renderAll(allMessages);
  }catch(e){ console.warn('Could not load live conversation', e); }
}
loadConversation();

async function sendMessage(sender, source, text, gestureKey){
  if(!text || !text.trim()) return;
  try{
    const res = await fetch('/api/live/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender, source, text: text.trim(), gesture_key: gestureKey || null }),
    });
    const data = await res.json();
    if(!res.ok) return;
    allMessages.push(data.translation);
    renderMessage(leftList, data.translation);
    renderMessage(rightList, data.translation);
    // Deaf-side replies are read aloud for the hearing person (per the Speech->...->Speech Output flow).
    if(sender === 'deaf'){
      speak(text);
      document.getElementById('liveReplySuggestions').innerHTML = '';
    } else {
      fetchLiveReplySuggestions(text);
    }
  }catch(e){ console.warn('Could not send live message', e); }
}

/* ---------- AI quick-reply suggestions for the Deaf user, based on what the hearing person just said ---------- */
async function fetchLiveReplySuggestions(transcript){
  const container = document.getElementById('liveReplySuggestions');
  try{
    const res = await fetch('/api/predict/reply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript }),
    });
    const data = await res.json();
    container.innerHTML = '';
    (data.suggestions || []).forEach((s, i) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'suggestion-chip';
      chip.style.animationDelay = `${i * 40}ms`;
      chip.innerHTML = `${s.text}<span class="conf">${s.confidence}%</span>`;
      chip.addEventListener('click', () => sendMessage('deaf', 'text', s.text, null));
      container.appendChild(chip);
    });
  }catch(e){ /* non-fatal */ }
}

/* ---------- Hearing person: speech + typed input ---------- */
const liveMicBtn = document.getElementById('liveMicBtn');
let liveRecognition = null, liveListening = false;
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if(SR){
  liveRecognition = new SR();
  liveRecognition.continuous = true;
  liveRecognition.interimResults = false;
  liveRecognition.lang = 'en-US';
  liveRecognition.onresult = (event) => {
    const text = event.results[event.results.length - 1][0].transcript;
    sendMessage('hearing', 'speech', text, null);
  };
  liveRecognition.onerror = () => stopLiveListening();
  liveRecognition.onend = () => { if(liveListening) liveRecognition.start(); };
} else {
  liveMicBtn.textContent = 'Speech recognition not supported in this browser.';
}
function startLiveListening(){
  if(!liveRecognition) return;
  liveListening = true; liveRecognition.start();
  liveMicBtn.classList.add('listening');
  liveMicBtn.textContent = '🔴 Listening… tap to stop';
}
function stopLiveListening(){
  liveListening = false;
  if(liveRecognition) liveRecognition.stop();
  liveMicBtn.classList.remove('listening');
  liveMicBtn.textContent = '🎤 Tap to speak';
}
liveMicBtn.addEventListener('click', () => { liveListening ? stopLiveListening() : startLiveListening(); });

const hearingInput = document.getElementById('liveHearingInput');
document.getElementById('liveHearingSend').addEventListener('click', () => {
  sendMessage('hearing', 'text', hearingInput.value);
  hearingInput.value = '';
});
hearingInput.addEventListener('keydown', (e) => {
  if(e.key === 'Enter'){ e.preventDefault(); sendMessage('hearing', 'text', hearingInput.value); hearingInput.value = ''; }
});

/* ---------- Deaf user: typed reply ---------- */
const deafInput = document.getElementById('liveDeafInput');
document.getElementById('liveDeafSend').addEventListener('click', () => {
  sendMessage('deaf', 'text', deafInput.value);
  deafInput.value = '';
});
deafInput.addEventListener('keydown', (e) => {
  if(e.key === 'Enter'){ e.preventDefault(); sendMessage('deaf', 'text', deafInput.value); deafInput.value = ''; }
});

/* ---------- Deaf user: sign camera ---------- */
const liveVideo = document.getElementById('liveVideo');
const liveOverlay = document.getElementById('liveOverlay');
const liveCtx = liveOverlay.getContext('2d');
const liveCamOff = document.getElementById('liveCamOff');
let liveCamera = null, liveHands = null;
let GESTURES = {};
let stableGesture = null, stableCount = 0, lastSigned = null;

fetch('/api/gestures').then(r => r.json()).then(list => {
  list.forEach(g => { GESTURES[g.gesture_key] = { word: g.word, emoji: g.emoji }; });
}).catch(() => {});

function dist(a, b){ return Math.hypot(a.x - b.x, a.y - b.y); }
function classifyGesture(lm){
  const wrist = lm[0];
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
  extended.thumb = dist(fingers.thumb.tip, lm[17]) > dist(fingers.thumb.mcp, lm[17]) * 1.1;
  const count = Object.values(extended).filter(Boolean).length;
  if(extended.thumb && extended.index && !extended.middle && !extended.ring && extended.pinky) return 'ILY';
  if(count >= 4) return 'OPEN_HAND';
  if(count === 0) return 'FIST';
  if(extended.index && extended.middle && !extended.ring && !extended.pinky) return 'PEACE';
  if(extended.index && !extended.middle && !extended.ring && !extended.pinky && !extended.thumb) return 'ONE';
  if(extended.thumb && !extended.index && !extended.middle && !extended.ring && !extended.pinky) return 'THUMB';
  return null;
}

function onLiveResults(results){
  liveOverlay.width = liveVideo.videoWidth || 640;
  liveOverlay.height = liveVideo.videoHeight || 360;
  liveCtx.save();
  liveCtx.clearRect(0, 0, liveOverlay.width, liveOverlay.height);
  if(results.multiHandLandmarks && results.multiHandLandmarks.length > 0){
    const lm = results.multiHandLandmarks[0];
    if(window.drawConnectors){
      drawConnectors(liveCtx, lm, Hands.HAND_CONNECTIONS, { color: '#3FD9C7', lineWidth: 3 });
      drawLandmarks(liveCtx, lm, { color: '#F2A33E', lineWidth: 1, radius: 3 });
    }
    const g = classifyGesture(lm);
    if(g && g === stableGesture){ stableCount++; } else { stableGesture = g; stableCount = 0; }
    if(g && stableCount === 6 && GESTURES[g] && lastSigned !== g){
      sendMessage('deaf', 'sign', GESTURES[g].word, g);
      lastSigned = g;
    }
    if(!g) lastSigned = null;
  }
  liveCtx.restore();
}

liveHands = new Hands({ locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${f}` });
liveHands.setOptions({ maxNumHands: 1, modelComplexity: 1, minDetectionConfidence: 0.6, minTrackingConfidence: 0.6 });
liveHands.onResults(onLiveResults);

document.getElementById('liveStartCam').addEventListener('click', async () => {
  try{
    liveCamOff.style.display = 'none';
    liveCamera = new Camera(liveVideo, {
      onFrame: async () => { await liveHands.send({ image: liveVideo }); },
      width: 640, height: 360,
    });
    await liveCamera.start();
    document.getElementById('liveStartCam').disabled = true;
    document.getElementById('liveStopCam').disabled = false;
  }catch(e){
    liveCamOff.style.display = 'flex';
    liveCamOff.textContent = 'Camera access was blocked or unavailable.';
  }
});
document.getElementById('liveStopCam').addEventListener('click', () => {
  if(liveCamera) liveCamera.stop();
  const stream = liveVideo.srcObject;
  if(stream) stream.getTracks().forEach(t => t.stop());
  liveCamOff.style.display = 'flex';
  liveCamOff.textContent = 'Camera stopped.';
  document.getElementById('liveStartCam').disabled = false;
  document.getElementById('liveStopCam').disabled = true;
  liveCtx.clearRect(0, 0, liveOverlay.width, liveOverlay.height);
});

/* ---------- Clear / export ---------- */
document.getElementById('liveClearBtn').addEventListener('click', async () => {
  await fetch('/api/live/messages', { method: 'DELETE' });
  allMessages = [];
  renderAll([]);
});
document.getElementById('liveExportBtn').addEventListener('click', () => {
  window.location.href = '/api/live/export';
});