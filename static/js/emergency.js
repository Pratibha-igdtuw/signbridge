/* ===================== Emergency Mode ===================== */

const bigText = document.getElementById('emergencyBigText');
const speakToggle = document.getElementById('emgSpeakToggle');

function speak(text){
  if(!speakToggle.checked) return;
  try{
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 0.9;
    speechSynthesis.cancel();
    speechSynthesis.speak(utt);
  }catch(e){ console.warn('TTS unavailable', e); }
}

async function logEmergency(source, text, gestureKey){
  try{
    if(window.SignBridgeOffline){
      await window.SignBridgeOffline.queueOrSend('emergency', '/api/emergency/log', { source, text, gesture_key: gestureKey || null });
      return;
    }
    await fetch('/api/emergency/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source, text, gesture_key: gestureKey || null }),
    });
  }catch(e){ console.warn('Could not log emergency message', e); }
}

function showBig(text){
  bigText.textContent = text;
  bigText.classList.remove('emg-fade-in');
  void bigText.offsetWidth; // restart the CSS fade-in animation on each change
  bigText.classList.add('emg-fade-in');
}

/* ---------- Current Message panel: Speak Again / Clear (UI-only, no new backend calls) ---------- */
const DEFAULT_MESSAGE = 'Tap a phrase — it will be spoken aloud and shown here.';
const emgSpeakAgainBtn = document.getElementById('emgSpeakAgain');
const emgClearBtn = document.getElementById('emgClearMessage');
if(emgSpeakAgainBtn){
  emgSpeakAgainBtn.addEventListener('click', () => {
    if(bigText.textContent && bigText.textContent !== DEFAULT_MESSAGE) speak(bigText.textContent);
  });
}
if(emgClearBtn){
  emgClearBtn.addEventListener('click', () => showBig(DEFAULT_MESSAGE));
}

/* ---------- Quick phrase buttons ---------- */
document.querySelectorAll('.emergency-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const phrase = btn.dataset.phrase;
    showBig(phrase);
    speak(phrase);
    logEmergency('text', phrase, null);
  });
});

/* ---------- Speech -> Text ---------- */
const emgMicBtn = document.getElementById('emgMicBtn');
const emgTranscript = document.getElementById('emgTranscript');
let emgRecognition = null, emgListening = false;

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if(SR){
  emgRecognition = new SR();
  emgRecognition.continuous = true;
  emgRecognition.interimResults = false;
  emgRecognition.lang = 'en-US';
  emgRecognition.onresult = (event) => {
    const text = event.results[event.results.length - 1][0].transcript;
    if(emgTranscript.querySelector('.empty')) emgTranscript.innerHTML = '';
    const div = document.createElement('div');
    div.className = 'line';
    div.textContent = text;
    emgTranscript.appendChild(div);
    emgTranscript.scrollTop = emgTranscript.scrollHeight;
    showBig(text);
    logEmergency('voice', text, null);
  };
  emgRecognition.onerror = () => stopEmgListening();
  emgRecognition.onend = () => { if(emgListening) emgRecognition.start(); };
} else {
  const label = emgMicBtn.querySelector('.emg-mic-label') || emgMicBtn;
  label.textContent = 'Speech recognition not supported in this browser.';
}

function startEmgListening(){
  if(!emgRecognition) return;
  emgListening = true;
  emgRecognition.start();
  emgMicBtn.classList.add('listening');
  const label = emgMicBtn.querySelector('.emg-mic-label') || emgMicBtn;
  label.textContent = 'Listening… tap to stop';
}
function stopEmgListening(){
  emgListening = false;
  if(emgRecognition) emgRecognition.stop();
  emgMicBtn.classList.remove('listening');
  const label = emgMicBtn.querySelector('.emg-mic-label') || emgMicBtn;
  label.textContent = 'Tap to start listening';
}
emgMicBtn.addEventListener('click', () => { emgListening ? stopEmgListening() : startEmgListening(); });

/* ---------- Sign -> Text (reuses the same six-shape geometry classifier) ---------- */
const emgVideo = document.getElementById('emgVideo');
const emgOverlay = document.getElementById('emgOverlay');
const emgCtx = emgOverlay.getContext('2d');
const emgCamOff = document.getElementById('emgCamOff');
let emgCamera = null, emgHands = null;
let GESTURES = {};
let stableGesture = null, stableCount = 0, lastSpoken = null;

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

function onEmgResults(results){
  emgOverlay.width = emgVideo.videoWidth || 640;
  emgOverlay.height = emgVideo.videoHeight || 480;
  emgCtx.save();
  emgCtx.clearRect(0, 0, emgOverlay.width, emgOverlay.height);
  if(results.multiHandLandmarks && results.multiHandLandmarks.length > 0){
    const lm = results.multiHandLandmarks[0];
    if(window.drawConnectors){
      drawConnectors(emgCtx, lm, Hands.HAND_CONNECTIONS, { color: '#3FD9C7', lineWidth: 3 });
      drawLandmarks(emgCtx, lm, { color: '#F2A33E', lineWidth: 1, radius: 3 });
    }
    const g = classifyGesture(lm);
    if(g && g === stableGesture){ stableCount++; } else { stableGesture = g; stableCount = 0; }
    if(g && stableCount === 6 && GESTURES[g] && lastSpoken !== g){
      const info = GESTURES[g];
      showBig(info.word);
      speak(info.word);
      logEmergency('sign', info.word, g);
      lastSpoken = g;
    }
    if(!g) lastSpoken = null;
  }
  emgCtx.restore();
}

emgHands = new Hands({ locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${f}` });
emgHands.setOptions({ maxNumHands: 1, modelComplexity: 1, minDetectionConfidence: 0.6, minTrackingConfidence: 0.6 });
emgHands.onResults(onEmgResults);

document.getElementById('emgStartCam').addEventListener('click', async () => {
  try{
    emgCamOff.style.display = 'none';
    emgCamera = new Camera(emgVideo, {
      onFrame: async () => { await emgHands.send({ image: emgVideo }); },
      width: 640, height: 400,
    });
    await emgCamera.start();
    document.getElementById('emgStartCam').disabled = true;
    document.getElementById('emgStopCam').disabled = false;
  }catch(e){
    emgCamOff.style.display = 'flex';
    emgCamOff.textContent = 'Camera access was blocked or unavailable.';
  }
});
document.getElementById('emgStopCam').addEventListener('click', () => {
  if(emgCamera) emgCamera.stop();
  const stream = emgVideo.srcObject;
  if(stream) stream.getTracks().forEach(t => t.stop());
  emgCamOff.style.display = 'flex';
  emgCamOff.textContent = 'Camera stopped.';
  document.getElementById('emgStartCam').disabled = false;
  document.getElementById('emgStopCam').disabled = true;
  emgCtx.clearRect(0, 0, emgOverlay.width, emgOverlay.height);
});