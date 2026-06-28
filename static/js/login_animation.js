/**
 * IDon Portal — Login Panel Animation
 * Combines floating data particles (bg) + scrolling audit log (fg)
 *
 * Usage:
 *   1. Add <canvas id="loginCanvas"></canvas> inside your left panel div
 *   2. Add these CSS rules to your stylesheet (or <style> block)
 *   3. Include this script at the bottom of your HTML (before </body>)
 */

/* ─── CSS to add to your stylesheet ────────────────────────────────────────

.login-left {
  position: relative;        // must be relative/absolute/fixed
  overflow: hidden;          // keeps canvas clipped to panel
}

#loginCanvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;      // clicks pass through to content below
  z-index: 0;
}

.login-left > *:not(canvas) {
  position: relative;
  z-index: 1;                // keeps text above the canvas
}

────────────────────────────────────────────────────────────────────────── */

(function () {
  const canvas = document.getElementById('loginCanvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let W, H, animId;

  // ── Resize handler ────────────────────────────────────────────────────────
  function resize() {
    W = canvas.width  = canvas.offsetWidth;
    H = canvas.height = canvas.offsetHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // ── Reduced-motion check ──────────────────────────────────────────────────
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReduced) return; // respect accessibility preference

  // ── Particle layer config ─────────────────────────────────────────────────
  const SYMBOLS = ['#', '01', '@', 'ID', '√', '▸', '✓', '∑', '◆', '//'];
  const PARTICLE_COUNT = 24;

  const particles = Array.from({ length: PARTICLE_COUNT }, () => spawnParticle(true));

  function spawnParticle(randomY) {
    return {
      x:       Math.random() * (W || 400),
      y:       randomY ? Math.random() * (H || 600) : (H || 600) + 10,
      speed:   0.22 + Math.random() * 0.38,
      opacity: 0.12 + Math.random() * 0.20,
      symbol:  SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)],
      size:    9 + Math.random() * 4,
      drift:   (Math.random() - 0.5) * 0.18,
    };
  }

  // ── Audit log layer config ────────────────────────────────────────────────
  const LOG_ROWS = [
    'LOGIN   admin         OK  hash:a3f9c2b1',
    'VIEW    student/42    OK  hash:b2e1d8f4',
    'EDIT    grade/CS101   OK  hash:c5d8f4a2',
    'LOGIN   faculty       OK  hash:d4a2b1e9',
    'EXPORT  report.pdf    OK  hash:e9f3a7c3',
    'LOGIN   student/7     OK  hash:f1b7e3d5',
    'VIEW    attendance    OK  hash:g8c4d2f1',
    'CALC    SGPA/batch2   OK  hash:h3e6f9b8',
    'UPDATE  profile/21    OK  hash:i7a1c5e2',
    'LOGIN   admin         OK  hash:j2f4b9d6',
  ];

  const LINE_HEIGHT = 21;
  let logOffset = 0;       // scroll offset in px
  let tick = 0;
  const ACTIVE_ROW = 4;    // which row gets the "live" highlight

  // ── Main draw loop ────────────────────────────────────────────────────────
  function draw() {
    ctx.clearRect(0, 0, W, H);
    tick++;

    drawParticles();
    drawAuditLog();
    drawEdgeFades();

    animId = requestAnimationFrame(draw);
  }

  function drawParticles() {
    particles.forEach((p, i) => {
      p.y -= p.speed;
      p.x += p.drift;

      if (p.y < -20) {
        particles[i] = spawnParticle(false);
        return;
      }

      const edgeFade = Math.min(p.y / 80, 1);
      ctx.save();
      ctx.globalAlpha = p.opacity * edgeFade;
      ctx.font = `${p.size}px monospace`;
      ctx.fillStyle = '#3a9e7e';
      ctx.fillText(p.symbol, p.x, p.y);
      ctx.restore();
    });
  }

  function drawAuditLog() {
    logOffset = (logOffset + 0.32) % LINE_HEIGHT;

    const startY    = -LINE_HEIGHT + logOffset;
    const totalRows = Math.ceil((H + LINE_HEIGHT) / LINE_HEIGHT) + 1;

    for (let i = 0; i < totalRows; i++) {
      const y   = startY + i * LINE_HEIGHT;
      const row = LOG_ROWS[i % LOG_ROWS.length];

      // fade near top and bottom
      const edgeFade = Math.min(y / 80, 1) * Math.min((H - y) / 90, 1);
      if (edgeFade <= 0) continue;

      const isActive = (i === ACTIVE_ROW);

      // highlight bar for active row
      if (isActive) {
        ctx.fillStyle = 'rgba(58,158,126,0.07)';
        ctx.fillRect(0, y - LINE_HEIGHT + 5, W, LINE_HEIGHT);
      }

      ctx.save();
      ctx.font = '10.5px monospace';
      const alpha = isActive ? 0.85 : 0.35;
      ctx.fillStyle = `rgba(58,158,126,${alpha * edgeFade})`;
      ctx.fillText(row, 22, y);

      // blinking cursor on active row
      if (isActive && Math.floor(Date.now() / 520) % 2 === 0) {
        const tw = ctx.measureText(row).width;
        ctx.fillStyle = 'rgba(58,158,126,0.65)';
        ctx.fillRect(22 + tw + 3, y - 12, 5, 13);
      }

      ctx.restore();
    }
  }

  function drawEdgeFades() {
    // top fade
    const topGrad = ctx.createLinearGradient(0, 0, 0, 72);
    topGrad.addColorStop(0, 'rgba(15,25,35,1)');
    topGrad.addColorStop(1, 'rgba(15,25,35,0)');
    ctx.fillStyle = topGrad;
    ctx.fillRect(0, 0, W, 72);

    // bottom fade
    const botGrad = ctx.createLinearGradient(0, H - 80, 0, H);
    botGrad.addColorStop(0, 'rgba(15,25,35,0)');
    botGrad.addColorStop(1, 'rgba(15,25,35,1)');
    ctx.fillStyle = botGrad;
    ctx.fillRect(0, H - 80, W, 80);
  }

  draw();
})();
