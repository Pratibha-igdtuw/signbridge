/* ===================== Practice Mode: camera pipeline + Smart Recognition Feedback =====================
   This intentionally duplicates the small amount of hand-geometry logic from app.js rather than
   importing it, so the For You translator page (app.js) can't be affected by anything here. */

const LESSON = window.LESSON;

const pVideo = document.getElementById('pVideo');
const pOverlay = document.getElementById('pOverlay');
const pCtx = pOverlay.getContext('2d');
const pCamOff = document.getElementById('pCamOff');

const practiceResultEl = document.getElementById('practiceResult');
const pConfidenceEl = document.getElementById('pConfidence');
const pAttemptsEl = document.getElementById('pAttempts');
const pSuccessRateEl = document.getElementById('pSuccessRate');

let pCamera = null, pHands = null;
let attemptsCount = 0;
let lastLoggedAt = 0;
let stableKey = null, stableCount = 0;

/* ---------- hidden canvas used only to sample average brightness for the lighting check ---------- */
const lightCanvas = document.createElement('canvas');
lightCanvas.width = 32; lightCanvas.height = 24;
const lightCtx = lightCanvas.getContext('2d', { willReadFrequently: true });

function sampleLighting(){
  if(!pVideo.videoWidth) return null;
  lightCtx.drawImage(pVideo, 0, 0, lightCanvas.width, lightCanvas.height);
  const { data } = lightCtx.getImageData(0, 0, lightCanvas.width, lightCanvas.height);
  let sum = 0;
  for(let i = 0; i < data.length; i += 4){
    sum += 0.299*data[i] + 0.587*data[i+1] + 0.114*data[i+2];
  }
  return sum / (data.length / 4); // 0-255 average luminance
}

/* ---------- geometry helpers (mirrors app.js classifyGesture, plus confidence + numbers) ---------- */
function dist(a, b){ return Math.hypot(a.x - b.x, a.y - b.y); }

function fingerGeometry(lm){
  const wrist = lm[0];
  const fingers = {
    thumb:  { tip: lm[4],  pip: lm[3],  mcp: lm[2] },
    index:  { tip: lm[8],  pip: lm[6] },
    middle: { tip: lm[12], pip: lm[10] },
    ring:   { tip: lm[16], pip: lm[14] },
    pinky:  { tip: lm[20], pip: lm[18] },
  };
  const ratios = {};
  const extended = {};
  for(const name of ['index','middle','ring','pinky']){
    const f = fingers[name];
    const ratio = dist(f.tip, wrist) / (dist(f.pip, wrist) || 0.0001);
    ratios[name] = ratio;
    extended[name] = ratio > 1.15;
  }
  const thumbRatio = dist(fingers.thumb.tip, lm[17]) / (dist(fingers.thumb.mcp, lm[17]) || 0.0001);
  ratios.thumb = thumbRatio;
  extended.thumb = thumbRatio > 1.1;
  return { extended, ratios };
}

function classifyShape(extended){
  const count = ['index','middle','ring','pinky'].filter(k => extended[k]).length;
  if(extended.thumb && extended.index && !extended.middle && !extended.ring && extended.pinky) return 'ILY';
  if(count >= 4) return 'OPEN_HAND';
  if(count === 0 && !extended.thumb) return 'FIST';
  if(extended.index && extended.middle && !extended.ring && !extended.pinky) return 'PEACE';
  if(extended.index && !extended.middle && !extended.ring && !extended.pinky && !extended.thumb) return 'ONE';
  if(extended.thumb && !extended.index && !extended.middle && !extended.ring && !extended.pinky) return 'THUMB';
  return null;
}

// ASL-style counting handshapes for the Numbers category: index, index+middle,
// index+middle+ring, index+middle+ring+pinky, then all five including thumb.
function classifyNumber(extended){
  const seq = ['index','middle','ring','pinky'];
  let n = 0;
  for(const key of seq){ if(extended[key]) n++; else break; }
  if(n === 4 && extended.thumb) return 'NUM_5';
  if(n === 4) return 'NUM_4';
  if(n === 3) return 'NUM_3';
  if(n === 2) return 'NUM_2';
  if(n === 1) return 'NUM_1';
  return null;
}

// Confidence: average margin between each finger's ratio and the extend/curl threshold,
// scaled to 0-100. A hand held cleanly in the expected shape scores near 100; a borderline
// or shaky hand-shape scores lower — this is read directly off the same landmarks used to
// classify the gesture, not a random or simulated number.
function computeConfidence(ratios){
  const thresholds = { index: 1.15, middle: 1.15, ring: 1.15, pinky: 1.15, thumb: 1.1 };
  let total = 0, n = 0;
  for(const key in thresholds){
    const margin = Math.abs(ratios[key] - thresholds[key]) / thresholds[key];
    total += Math.min(1, margin * 2.2); // scale so a decisive pose approaches 1.0
    n++;
  }
  return Math.round((total / n) * 100);
}

function bboxFraction(lm){
  let minX=1, maxX=0, minY=1, maxY=0;
  lm.forEach(p => { minX=Math.min(minX,p.x); maxX=Math.max(maxX,p.x); minY=Math.min(minY,p.y); maxY=Math.max(maxY,p.y); });
  return Math.max(maxX-minX, maxY-minY);
}

function edgeClipped(lm){
  return lm.some(p => p.x < 0.03 || p.x > 0.97 || p.y < 0.03 || p.y > 0.97);
}

/* ---------- feedback UI ---------- */
function setDot(id, level){ // level: 'good' | 'average' | 'poor'
  const el = document.getElementById(id);
  el.className = 'dot ' + level;
}
function setFeedback(prefix, level, text){
  setDot('dot' + prefix, level);
  document.getElementById('fv' + prefix).textContent = text;
}

function showSuggestions(list){
  const box = document.getElementById('feedbackSuggestions');
  const ul = document.getElementById('feedbackSuggestionsList');
  if(!list.length){ box.classList.remove('show'); return; }
  ul.innerHTML = list.map(s => `<li>${s}</li>`).join('');
  box.classList.add('show');
}

function resetFeedbackIdle(){
  setFeedback('Detected', 'poor', '—');
  setFeedback('Confidence', 'poor', '—');
  setFeedback('Visibility', 'poor', 'No hand detected');
  setFeedback('Distance', 'poor', '—');
  document.getElementById('fvProcessing').textContent = 'Idle';
  setDot('dotProcessing', 'poor');
  showSuggestions([]);
}

/* ---------- attempt logging ---------- */
async function logAttempt(detectedKey, confidence){
  attemptsCount++;
  pAttemptsEl.textContent = attemptsCount;
  try{
    if(window.SignBridgeOffline){
      const result = await window.SignBridgeOffline.queueOrSend('practice', '/api/practice/attempt', {
        lesson_key: LESSON.key, detected_gesture: detectedKey, confidence,
      });
      if(result.queued){
        practiceResultEl.textContent = 'Saved offline — will sync automatically when you\'re back online.';
        practiceResultEl.className = 'practice-result';
        return;
      }
      if(!result.response) return;
      applyAttemptResult(result.response);
      return;
    }
    const res = await fetch('/api/practice/attempt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lesson_key: LESSON.key, detected_gesture: detectedKey, confidence }),
    });
    const data = await res.json();
    if(!res.ok) return;
    applyAttemptResult(data);
  }catch(e){ console.warn('Could not log practice attempt', e); }
}

function applyAttemptResult(data){
  pAttemptsEl.textContent = data.attempts_for_lesson;
  pSuccessRateEl.textContent = data.success_rate_for_lesson != null ? `${data.success_rate_for_lesson}%` : '—';

  if(LESSON.detectable){
    if(data.attempt.correct){
      practiceResultEl.textContent = '✓ Correct!';
      practiceResultEl.className = 'practice-result correct';
    } else {
      practiceResultEl.textContent = '✗ Try Again';
      practiceResultEl.className = 'practice-result incorrect';
    }
  } else {
    practiceResultEl.textContent = 'Practice attempt logged — nice work!';
    practiceResultEl.className = 'practice-result';
  }
}

/* ---------- MediaPipe results handler ---------- */
function onResults(results){
  pOverlay.width = pVideo.videoWidth || 640;
  pOverlay.height = pVideo.videoHeight || 480;
  pCtx.save();
  pCtx.clearRect(0, 0, pOverlay.width, pOverlay.height);

  const lighting = sampleLighting();
  if(lighting != null){
    if(lighting > 90) setFeedback('Lighting', 'good', 'Good');
    else if(lighting > 45) setFeedback('Lighting', 'average', 'Average');
    else setFeedback('Lighting', 'poor', 'Poor — too dark');
  }

  if(results.multiHandLandmarks && results.multiHandLandmarks.length > 0){
    const lm = results.multiHandLandmarks[0];
    if(window.drawConnectors){
      drawConnectors(pCtx, lm, Hands.HAND_CONNECTIONS, { color: '#3FD9C7', lineWidth: 3 });
      drawLandmarks(pCtx, lm, { color: '#F2A33E', lineWidth: 1, radius: 3 });
    }

    document.getElementById('fvProcessing').textContent = 'Analyzing…';
    setDot('dotProcessing', 'good');

    const { extended, ratios } = fingerGeometry(lm);
    const shapeKey = LESSON.category === 'numbers' ? classifyNumber(extended) : classifyShape(extended);
    const confidence = computeConfidence(ratios);

    setFeedback('Detected', shapeKey ? 'good' : 'average', shapeKey || 'Unclear');
    setFeedback('Confidence', confidence >= 70 ? 'good' : confidence >= 40 ? 'average' : 'poor', `${confidence}%`);
    pConfidenceEl.textContent = `${confidence}%`;

    const clipped = edgeClipped(lm);
    setFeedback('Visibility', clipped ? 'average' : 'good', clipped ? 'Partially out of frame' : 'Fully visible');

    const size = bboxFraction(lm);
    let distanceLevel = 'good', distanceText = 'Good distance';
    if(size < 0.22){ distanceLevel = 'average'; distanceText = 'Too far — move closer'; }
    else if(size > 0.65){ distanceLevel = 'average'; distanceText = 'Too close — move back'; }
    setFeedback('Distance', distanceLevel, distanceText);

    const suggestions = [];
    if(confidence < 55) suggestions.push('Hold the gesture steady for a full second.');
    if(clipped) suggestions.push('Keep one hand fully visible inside the camera frame.');
    if(size < 0.22) suggestions.push('Move closer to the camera.');
    if(size > 0.65) suggestions.push('Move back slightly — your hand is very close to the lens.');
    if(lighting != null && lighting < 45) suggestions.push('Improve lighting — face a light source if possible.');
    showSuggestions(suggestions);

    if(shapeKey && shapeKey === stableKey){ stableCount++; } else { stableKey = shapeKey; stableCount = 0; }

    if(LESSON.detectable && shapeKey && stableCount === 6 && Date.now() - lastLoggedAt > 1500){
      lastLoggedAt = Date.now();
      logAttempt(shapeKey, confidence);
    }
  } else {
    setFeedback('Distance', 'poor', '—');
    document.getElementById('fvProcessing').textContent = 'Waiting for hand';
    setDot('dotProcessing', 'average');
    setFeedback('Visibility', 'poor', 'No hand detected');
    setFeedback('Detected', 'poor', '—');
    setFeedback('Confidence', 'poor', '—');
    pConfidenceEl.textContent = '—';
    stableKey = null; stableCount = 0;
    showSuggestions(['Show one hand clearly to the camera to begin.']);
  }
  pCtx.restore();
}

pHands = new Hands({ locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${f}` });
pHands.setOptions({ maxNumHands: 1, modelComplexity: 1, minDetectionConfidence: 0.6, minTrackingConfidence: 0.6 });
pHands.onResults(onResults);

document.getElementById('pStartCam').addEventListener('click', async () => {
  try{
    pCamOff.style.display = 'none';
    pCamera = new Camera(pVideo, {
      onFrame: async () => { await pHands.send({ image: pVideo }); },
      width: 640, height: 480,
    });
    await pCamera.start();
    document.getElementById('pStartCam').disabled = true;
    document.getElementById('pStopCam').disabled = false;
    setFeedback('Camera', 'good', 'Active');
    const logBtn = document.getElementById('pLogFreePractice');
    if(logBtn) logBtn.disabled = false;
  }catch(e){
    pCamOff.style.display = 'flex';
    pCamOff.textContent = 'Camera access was blocked or unavailable. Try opening this page directly in Chrome on your own device.';
  }
});

document.getElementById('pStopCam').addEventListener('click', () => {
  if(pCamera){ pCamera.stop(); }
  const stream = pVideo.srcObject;
  if(stream){ stream.getTracks().forEach(t => t.stop()); }
  pCamOff.style.display = 'flex';
  pCamOff.textContent = 'Camera stopped.';
  document.getElementById('pStartCam').disabled = false;
  document.getElementById('pStopCam').disabled = true;
  pCtx.clearRect(0, 0, pOverlay.width, pOverlay.height);
  setFeedback('Camera', 'poor', 'Off');
  resetFeedbackIdle();
  const logBtn = document.getElementById('pLogFreePractice');
  if(logBtn) logBtn.disabled = true;
});

const freeBtn = document.getElementById('pLogFreePractice');
if(freeBtn){
  freeBtn.addEventListener('click', () => {
    const confidence = pConfidenceEl.textContent.endsWith('%') ? parseInt(pConfidenceEl.textContent) : null;
    logAttempt(null, confidence);
  });
}

resetFeedbackIdle();

/* ---------- pull current success rate on load so the tile isn't blank ---------- */
(async () => {
  try{
    const res = await fetch('/api/learn/progress');
    const s = await res.json();
    const cat = (s.top_categories || []).find(c => c.category === LESSON.category);
    if(cat && cat.attempts) pSuccessRateEl.textContent = `${Math.round((cat.correct / cat.attempts) * 100)}%`;
  }catch(e){ /* non-fatal */ }
})();