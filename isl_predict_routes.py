"""
ISL (Indian Sign Language) word-level sign detection — quick-demo integration.

This proxies short camera clips to a public Hugging Face Space running a
fine-tuned Swin3D-S video model, from the MIT-licensed Uni-Creator/signBridge
project: https://github.com/Uni-Creator/signBridge

IMPORTANT — this is a third-party dependency, not something SignBridge owns
or controls:
  - The HF Space (https://creator-090-isl-api.hf.space) is someone else's
    free-tier deployment. It can go offline, cold-start slowly, rate-limit,
    or change its response shape at any time without notice.
  - It recognizes 76 fixed ISL words (a different vocabulary from this
    project's built-in ASL/BSL/ISL gesture list) and reports ~67% top-1
    accuracy on its own test set — treat predictions as a demo, not a
    guarantee.
  - For a graded submission or production use, this dependency should be
    disclosed, and ideally replaced with a self-hosted copy of the model
    before relying on it long-term.

Kept server-side (rather than called directly from the browser) so:
  1. The browser never needs CORS access to a third-party host.
  2. Swapping this out for a self-hosted model later only means changing
     the two URLs below — no frontend changes required.
"""
import time

import requests
from flask import Blueprint, request, jsonify

from auth import login_required

isl_predict_bp = Blueprint('isl_predict', __name__)

_HF_BASE_URL = "https://creator-090-isl-api.hf.space"
_PREDICT_FRAMES_URL = f"{_HF_BASE_URL}/predict_frames"
_HEALTH_URL = f"{_HF_BASE_URL}/health"

_CLIP_LENGTH = 16  # the external model requires exactly 16 frames per clip

_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0)
_session.mount("https://", _adapter)


@isl_predict_bp.route('/api/isl/health', methods=['GET'])
@login_required
def isl_health():
    """Lets the frontend show 'model warming up' instead of a raw timeout —
    Hugging Face Spaces on the free tier sleep after inactivity."""
    try:
        r = _session.get(_HEALTH_URL, timeout=3)
        healthy = r.status_code == 200 and r.json().get('status') == 'ok'
    except requests.RequestException:
        healthy = False
    return jsonify({'healthy': healthy})


@isl_predict_bp.route('/api/isl/predict/frames', methods=['POST'])
@login_required
def isl_predict_frames():
    """
    Body: { frames: ["<base64 jpeg>", ... exactly 16] }
    Returns: { prediction: "<word>", confidence: 0..1 } or { error: "..." }
    """
    data = request.get_json(force=True, silent=True) or {}
    frames = data.get('frames')

    if not isinstance(frames, list) or len(frames) != _CLIP_LENGTH:
        got = len(frames) if isinstance(frames, list) else 0
        return jsonify({'error': f'Exactly {_CLIP_LENGTH} frames required, got {got}'}), 400

    payload = {'frames': frames, 'top_k': 1}
    last_err = 'Unknown error'

    for attempt in range(2):
        try:
            t0 = time.time()
            r = _session.post(_PREDICT_FRAMES_URL, json=payload, timeout=15)
            if r.status_code == 200:
                result = r.json()
                result['total_latency_ms'] = round((time.time() - t0) * 1000, 2)
                return jsonify(result)
            if r.status_code == 503:
                time.sleep(1.5)
                continue
            last_err = f'ISL API error {r.status_code}'
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(0.5)

    return jsonify({'error': last_err}), 502