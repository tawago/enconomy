/* PoP web QR scanner (window.popQr), used by QrScanner in Pairing.web.kt.
 * scan() opens a fullscreen overlay above the Compose canvas: rear camera <video>, BarcodeDetector when the
 * browser has it, else jsQR (handed over by the app through setDecoder) on a canvas at ~8 fps. A text field
 * takes a pasted pop1: code. Resolves with the text, or null when closed.
 */
(function () {
  'use strict';
  let decoder = null;   // jsQR(rgba, w, h)
  let cur = null;       // { resolve, stream, timer, el }

  function css(el, s) { el.style.cssText = s; return el; }

  function finish(text) {
    if (!cur) return;
    const c = cur;
    cur = null;
    if (c.timer) clearTimeout(c.timer);
    if (c.stream) c.stream.getTracks().forEach((t) => t.stop());
    if (c.el && c.el.parentNode) c.el.parentNode.removeChild(c.el);
    c.resolve(text);
  }

  function scan() {
    finish(null);
    return new Promise((resolve) => {
      const el = css(document.createElement('div'),
        'position:fixed;inset:0;z-index:1000;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;font:15px system-ui,sans-serif;color:#fff');
      const video = css(document.createElement('video'), 'width:100%;max-width:560px;max-height:65vh;object-fit:cover;border-radius:12px');
      video.setAttribute('playsinline', ''); video.muted = true;
      const note = css(document.createElement('div'), 'opacity:.8;padding:0 16px;text-align:center');
      note.textContent = 'Point the camera at the host\'s QR code';
      const row = css(document.createElement('div'), 'display:flex;gap:8px;width:100%;max-width:560px;padding:0 16px;box-sizing:border-box');
      const input = css(document.createElement('input'), 'flex:1;min-width:0;padding:10px;border-radius:8px;border:0;font:inherit');
      input.placeholder = 'or paste pop1:… here';
      const go = css(document.createElement('button'), 'padding:10px 14px;border-radius:8px;border:0;font:inherit');
      go.textContent = 'Use';
      const close = css(document.createElement('button'), 'padding:10px 20px;border-radius:8px;border:1px solid #fff;background:transparent;color:#fff;font:inherit');
      close.textContent = 'Close';
      row.append(input, go);
      el.append(video, note, row, close);
      document.body.appendChild(el);
      cur = { resolve, stream: null, timer: null, el };
      const mine = cur;

      go.onclick = () => { const t = input.value.trim(); if (t) finish(t); };
      input.onkeydown = (e) => { if (e.key === 'Enter') go.onclick(); };
      close.onclick = () => finish(null);

      const detector = ('BarcodeDetector' in window) ? new window.BarcodeDetector({ formats: ['qr_code'] }) : null;
      const canvas = document.createElement('canvas');
      const g = canvas.getContext('2d', { willReadFrequently: true });

      async function tick() {
        if (cur !== mine) return;
        try {
          if (video.readyState >= 2 && video.videoWidth > 0) {
            let text = null;
            if (detector) {
              const r = await detector.detect(video);
              if (r && r.length) text = r[0].rawValue;
            } else if (decoder) {
              const w = Math.min(640, video.videoWidth);
              const h = Math.round(video.videoHeight * w / video.videoWidth);
              canvas.width = w; canvas.height = h;
              g.drawImage(video, 0, 0, w, h);
              const img = g.getImageData(0, 0, w, h);
              const r = decoder(img.data, w, h);
              if (r && r.data) text = r.data;
            }
            if (text && cur === mine) { finish(text); return; }
          }
        } catch (e) {
          note.textContent = 'Scanner error: ' + (e && e.message || e);
        }
        if (cur === mine) mine.timer = setTimeout(tick, 125);
      }

      navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
        .then((s) => {
          if (cur !== mine) { s.getTracks().forEach((t) => t.stop()); return; }
          mine.stream = s;
          video.srcObject = s;
          return video.play().then(tick);
        })
        .catch((e) => { note.textContent = 'No camera (' + (e && e.message || e) + '). Paste the code instead.'; });
    });
  }

  window.popQr = {
    scan,
    close: () => finish(null),
    setDecoder: (f) => { decoder = f; },
  };
})();
