// Isolated world, top frame only, on every matched page. The whole login lives here. The page never calls us and we never call the page:
// it writes markup, we read it with getAttribute, and we write back one field and one state attribute.
//
// What counts as the user. Measured on Chrome 157: Chrome marks blur() and focus() from a script as trusted, marks
// execCommand's input as trusted, and marks the change after checkbox.click() as trusted. So e.isTrusted alone on those proves nothing.
//  - Text: a value counts only if every edit was a trusted input that matches a trusted keydown of that very key, a trusted paste of
//    that very text, or a trusted IME session, and the result is exactly the old value with that one edit. Anything else taints the
//    field until it's emptied.
//  - Leaving the field: a blur counts only right after a trusted Tab or a trusted pointerdown elsewhere. Script blur() and switching
//    windows don't count.
//  - Switch: only a trusted click. A script's click(), on the checkbox or its label, stays untrusted.
(() => {
  const FIELD = 'input[autocomplete="wvp"]', SWITCH = 'input[type="checkbox"][data-wvp-anonymous]', TOKEN = 'input[autocomplete="wvp-token"]';
  const is = (t, sel) => t instanceof HTMLInputElement && t.matches(sel);
  const fields = new WeakMap();
  const track = (f) => { let s = fields.get(f); if (!s) fields.set(f, s = { tracked: "", tainted: false, key: null, paste: null, ime: false, leftAt: 0, done: null }); return s; };
  // True if `now` is `old` with one range replaced by `data`.
  const isSplice = (old, now, data) => {
    for (let p = 0; p <= Math.min(old.length, now.length - data.length); p++) {
      if (old.slice(0, p) !== now.slice(0, p)) break;
      if (now.slice(p, p + data.length) !== data) continue;
      const rest = now.slice(p + data.length);
      if (old.length - rest.length >= p && old.endsWith(rest)) return true;
    }
    return false;
  };
  const inputOk = (e, s) => {
    if (s.ime) return true;
    if (s.paste !== null) return e.inputType === "insertFromPaste" && isSplice(s.tracked, e.target.value, s.paste);
    if (s.key === null) return false;
    if (e.inputType === "insertText") return e.data === s.key && isSplice(s.tracked, e.target.value, e.data);
    if (e.inputType.startsWith("delete")) return isSplice(s.tracked, e.target.value, "");
    return false;
  };

  window.addEventListener("keydown", (e) => {
    if (!e.isTrusted || !is(e.target, FIELD)) return;
    const s = track(e.target);
    s.key = e.key;
    if (e.key === "Tab") s.leftAt = performance.now();
    if (e.key === "Enter") {
      // Enter is a way of saying "done" too. Don't let the form go before the token is in.
      if (s.done !== doneKey(e.target)) { e.preventDefault(); named(e.target); }
    }
  }, true);
  window.addEventListener("paste", (e) => { if (e.isTrusted && is(e.target, FIELD)) track(e.target).paste = e.clipboardData?.getData("text/plain") ?? ""; }, true);
  window.addEventListener("compositionstart", (e) => { if (e.isTrusted && is(e.target, FIELD)) track(e.target).ime = true; }, true);
  window.addEventListener("compositionend", (e) => { if (e.isTrusted && is(e.target, FIELD)) { const s = track(e.target); s.ime = false; if (e.target.value !== s.tracked && !s.tainted) s.tracked = e.target.value; } }, true);
  window.addEventListener("beforeinput", (e) => {
    if (!e.isTrusted || !is(e.target, FIELD)) return;
    const s = track(e.target);
    if (e.target.value === "") { s.tracked = ""; s.tainted = false; } // An empty field can't carry anything forged.
  }, true);
  window.addEventListener("input", (e) => {
    if (!is(e.target, FIELD)) return;
    const s = track(e.target), v = e.target.value;
    if (e.isTrusted && inputOk(e, s)) s.tracked = v; else s.tainted = true;
    s.key = null; s.paste = null;
    if (v === "" && e.isTrusted) { s.tainted = false; s.tracked = ""; }
  }, true);
  window.addEventListener("pointerdown", (e) => {
    if (!e.isTrusted) return;
    const f = document.activeElement;
    if (!is(f, FIELD) || e.target === f) return;
    // Going to the switch means the user wants anonymous, so that's not "done typing".
    const sw = f.form?.querySelector(SWITCH);
    if (sw && (e.target === sw || sw.labels?.length && [...sw.labels].some((l) => l.contains(e.target)))) return;
    track(f).leftAt = performance.now();
  }, true);
  window.addEventListener("blur", (e) => {
    if (!e.isTrusted || !is(e.target, FIELD)) return;
    const s = track(e.target);
    const fresh = s.leftAt > 0 && performance.now() - s.leftAt < 1000;
    s.leftAt = 0;
    if (fresh) named(e.target);
  }, true);
  window.addEventListener("click", (e) => {
    if (!e.isTrusted || !is(e.target, SWITCH)) return;
    flip(e.target);
  }, true);

  // ---- what the page sees: the token, and one of working, done, none, idle. The reason never goes to the page. ----
  const tokenOf = (el) => el.form?.querySelector(TOKEN) ?? null;
  const setState = (tok, state) => { tok.setAttribute("data-wvp-state", state); tok.dispatchEvent(new Event("wvp-state", { bubbles: true })); };
  const clearToken = (tok) => { if (tok.value) { tok.value = ""; tok.dispatchEvent(new Event("input", { bubbles: true })); } };
  const doneKey = (f) => `${f.value}|${tokenOf(f)?.getAttribute("nonce") ?? ""}`;

  // Latest action wins. Older ones finish, then get dropped.
  let gen = 0, queue = Promise.resolve(), waiting = null;
  // Submit race. A submit while a proof runs waits for it, then goes. Otherwise the form leaves with an empty token.
  const working = new WeakSet(), heldSubmit = new WeakMap();
  window.addEventListener("submit", (e) => {
    const tok = e.target.querySelector?.(TOKEN);
    if (!tok || !working.has(tok)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    heldSubmit.set(tok, { form: e.target, submitter: e.submitter ?? undefined });
  }, true);
  const finish = (tok, ok) => {
    working.delete(tok);
    const h = heldSubmit.get(tok);
    heldSubmit.delete(tok);
    if (ok && h && h.form.isConnected) h.form.requestSubmit(h.submitter?.isConnected ? h.submitter : undefined);
  };
  function start(job) {
    job.gen = ++gen;
    waiting = null;
    working.add(job.tok);
    clearToken(job.tok);
    setState(job.tok, "working");
    queue = queue.then(() => run(job)).catch((e) => fail(job, String(e?.message ?? e)));
  }
  function named(f) {
    const tok = tokenOf(f), sw = f.form?.querySelector(SWITCH);
    if (!tok || f.readOnly || sw?.checked) return;
    const s = track(f);
    if (f.value === "") return;
    if (s.tainted || f.value !== s.tracked) {
      setState(tok, "none");
      notice(f, "No proof. The page filled this in, not you. Clear it and type it yourself.", "bad");
      return;
    }
    if (s.done === doneKey(f)) return;
    start({ mode: "name", tok, field: f, typed: f.value });
  }
  function flip(sw) {
    const tok = tokenOf(sw), f = sw.form?.querySelector(FIELD);
    if (!tok) return;
    if (f) f.readOnly = sw.checked;
    if (sw.checked) { start({ mode: "anon", tok, field: f, sw }); return; }
    gen++; waiting = null;
    finish(tok, false);
    clearToken(tok);
    if (f) track(f).done = null;
    setState(tok, "idle");
  }
  const fail = (job, msg) => { if (job.gen !== gen) return; finish(job.tok, false); setState(job.tok, "none"); notice(job.field ?? job.tok, msg, "bad"); };

  const ask = (method, args) => new Promise((ok, no) => {
    let answered = false;
    const port = chrome.runtime.connect({ name: "wvp" });
    port.onMessage.addListener((m) => { answered = true; port.disconnect(); if (m.err) no(Object.assign(new Error(m.err.message), { code: m.err.code })); else ok(m.ok); });
    port.onDisconnect.addListener(() => { if (!answered) no(Object.assign(new Error("The extension restarted. Try again."), { code: "extension_restarted" })); });
    port.postMessage({ method, args });
  });

  async function run(job) {
    if (job.gen !== gen) return;
    // getAttribute, like Chrome's EVP. A script setting el.nonce alone doesn't count.
    const nonce = job.tok.getAttribute("nonce") ?? "";
    let r;
    try {
      const a = (job.field ?? job.tok).getBoundingClientRect();
      r = await ask("prove", { mode: job.mode, typed: job.typed ?? null, nonce, rect: { x: a.x, y: a.y, width: a.width, height: a.height } });
    }
    catch (e) { return fail(job, WHY[e.code] ?? e.message); }
    if (job.gen !== gen) return;
    if (r.enroll) { waiting = job; notice(job.field ?? job.tok, "This browser has no valid credential. Finish the new tab, and this login continues by itself.", "info"); return; }
    // The page may have moved things while we proved. The proof is only for what was read at the start.
    const stillAnon = job.mode === "anon" ? job.sw.checked : job.field.value === job.typed;
    if (!job.tok.isConnected || job.tok.getAttribute("nonce") !== nonce || !stillAnon) return fail(job, "No proof delivered. The page changed the form while the proof ran.");
    job.tok.value = r.token;
    if (job.field && job.mode === "name") track(job.field).done = doneKey(job.field);
    setState(job.tok, "done");
    job.tok.dispatchEvent(new Event("input", { bubbles: true }));
    job.tok.dispatchEvent(new Event("change", { bubbles: true }));
    finish(job.tok, true);
    notice(job.field ?? job.tok, r.revealed ? `Proof made for this site. It shows: ${r.revealed}.` : "Hidden proof made for this site. It shows: a valid credential, nothing else.", "ok");
  }
  const WHY = {
    no_match: "No proof. That isn't the name or address this browser is enrolled for.",
    invalid: "No proof. That isn't an ENS name or a 0x address.",
    bad_nonce: "No proof. This site's challenge is missing or malformed.",
    busy: "Another proof is running. Try again in a moment.",
    no_activation: "No proof. That didn't come from a real click or key press.",
    user_denied: "No proof. You said no.",
  };
  chrome.runtime.onMessage.addListener((m, sender) => {
    if (sender.id !== chrome.runtime.id || m?.to !== "wvp-login" || !waiting) return;
    const job = waiting;
    waiting = null;
    if (m.kind === "resume") start(job);
    if (m.kind === "enroll-closed") fail(job, "Enrollment was closed, so no proof was made.");
  });

  // ---- the extension's own small notice. Closed shadow root: the page can't read it, but it can cover or remove it. ----
  let host, box, hideT;
  function notice(anchor, text, kind) {
    if (!host) {
      host = document.createElement("div");
      const root = host.attachShadow({ mode: "closed" });
      root.innerHTML = `<style>div{position:fixed;z-index:2147483647;max-width:420px;background:#18181b;color:#fff;font:13px/1.45 system-ui,sans-serif;padding:9px 12px;border-radius:9px;box-shadow:0 6px 20px #0004;border-left:4px solid var(--c)}b{display:block;font-size:11px;font-weight:600;color:#a1a1aa}</style><div><b>WVP extension</b><span></span></div>`;
      box = root.querySelector("div");
    }
    if (!host.isConnected) document.documentElement.append(host);
    const r = (anchor.form ?? anchor).getBoundingClientRect();
    box.style.left = `${Math.max(8, r.left)}px`;
    box.style.top = `${r.bottom + 88}px`;
    box.style.setProperty("--c", kind === "bad" ? "#ef4444" : kind === "ok" ? "#22c55e" : "#3b82f6");
    box.querySelector("span").textContent = text;
    host.style.display = "";
    clearTimeout(hideT);
    hideT = setTimeout(() => { host.style.display = "none"; }, kind === "bad" ? 12000 : 7000);
  }
})();
