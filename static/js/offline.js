/* ===================== SignBridge Offline Manager =====================
   Loaded on every page (see base.html / emergency.html). Provides:
   - navigator.onLine-based status badge (🟢 Offline Mode Enabled / 🔵 Online Mode)
   - an IndexedDB write-queue so Emergency Mode, translations, and practice
     attempts keep working with no connection, then auto-sync via /api/sync
   - a small read-through cache for /api/gestures and /api/learn/lessons so
     the Learn module and gesture vocabulary are usable offline too
   Exposed globally as `window.SignBridgeOffline`. */

const DB_NAME = 'signbridge_offline';
const DB_VERSION = 1;
const STORES = ['queue_translations', 'queue_emergency', 'queue_practice', 'cache'];

function openDB(){
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if(!db.objectStoreNames.contains('queue_translations')) db.createObjectStore('queue_translations', { autoIncrement: true });
      if(!db.objectStoreNames.contains('queue_emergency')) db.createObjectStore('queue_emergency', { autoIncrement: true });
      if(!db.objectStoreNames.contains('queue_practice')) db.createObjectStore('queue_practice', { autoIncrement: true });
      if(!db.objectStoreNames.contains('cache')) db.createObjectStore('cache', { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function addToQueue(store, item){
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    tx.objectStore(store).add(item);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function getAllFromQueue(store){
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly');
    const req = tx.objectStore(store).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

async function clearQueue(store){
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    tx.objectStore(store).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function setCache(key, value){
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('cache', 'readwrite');
    tx.objectStore('cache').put({ key, value, cachedAt: Date.now() });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function getCache(key){
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('cache', 'readonly');
    const req = tx.objectStore('cache').get(key);
    req.onsuccess = () => resolve(req.result ? req.result.value : null);
    req.onerror = () => reject(req.error);
  });
}

/* ---------- status badge ---------- */
function renderBadge(){
  let badge = document.getElementById('sbOfflineBadge');
  if(!badge){
    badge = document.createElement('div');
    badge.id = 'sbOfflineBadge';
    badge.className = 'offline-badge';
    document.body.appendChild(badge);
  }
  if(navigator.onLine){
    badge.textContent = '🔵 Online Mode';
    badge.className = 'offline-badge online';
  } else {
    badge.textContent = '🟢 Offline Mode Enabled';
    badge.className = 'offline-badge offline show';
  }
  if(navigator.onLine){
    // Briefly show "Online Mode" then fade, so it doesn't sit on screen permanently.
    badge.classList.add('show');
    setTimeout(() => badge.classList.remove('show'), 2500);
  }
}

function showToast(text){
  let toast = document.getElementById('sbSyncToast');
  if(!toast){
    toast = document.createElement('div');
    toast.id = 'sbSyncToast';
    toast.className = 'sync-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 3000);
}

/* ---------- queue-or-send: the main entry point other pages use for writes ---------- */
async function queueOrSend(kind, endpoint, payload){
  const storeMap = { translation: 'queue_translations', emergency: 'queue_emergency', practice: 'queue_practice' };
  const store = storeMap[kind];

  if(navigator.onLine){
    try{
      const res = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      if(res.ok) return { queued: false, response: await res.json() };
      // Non-network failure (validation error etc) — don't queue, surface it.
      return { queued: false, response: await res.json().catch(() => null), error: true };
    }catch(e){
      // Network error even though navigator.onLine said we're online (flaky connection) — queue it.
    }
  }
  await addToQueue(store, { ...payload, _queued_at: Date.now() });
  return { queued: true };
}

async function syncQueues(){
  const [translations, emergency_logs, practice_attempts] = await Promise.all([
    getAllFromQueue('queue_translations'),
    getAllFromQueue('queue_emergency'),
    getAllFromQueue('queue_practice'),
  ]);
  if(!translations.length && !emergency_logs.length && !practice_attempts.length) return;

  try{
    const res = await fetch('/api/sync', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ translations, emergency_logs, practice_attempts }),
    });
    if(res.ok){
      await Promise.all([clearQueue('queue_translations'), clearQueue('queue_emergency'), clearQueue('queue_practice')]);
      showToast('✓ Synced Successfully');
      document.dispatchEvent(new CustomEvent('signbridge:synced'));
    }
  }catch(e){ /* still offline or server unreachable — leave queue intact, try again next 'online' event */ }
}

/* ---------- read-through cache for GET data used offline (gestures, lessons) ---------- */
async function cachedGet(url, cacheKey){
  if(navigator.onLine){
    try{
      const res = await fetch(url);
      if(res.ok){
        const data = await res.json();
        setCache(cacheKey, data);
        return data;
      }
    }catch(e){ /* fall through to cache */ }
  }
  return await getCache(cacheKey);
}

/* ---------- boot ---------- */
renderBadge();
window.addEventListener('online', () => { renderBadge(); syncQueues(); });
window.addEventListener('offline', renderBadge);

if('serviceWorker' in navigator){
  navigator.serviceWorker.register('/sw.js').catch((e) => console.warn('Service worker registration failed', e));
}

// Try an initial sync in case items were queued in a previous offline session.
if(navigator.onLine) syncQueues();

window.SignBridgeOffline = { queueOrSend, cachedGet, syncQueues, isOnline: () => navigator.onLine };