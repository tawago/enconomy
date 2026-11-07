// Isolated world, top frame only, on every matched page. The whole login lives here. The page never calls us and we never call the page:
// it writes markup, we read it with getAttribute, and we write back one field and one state attribute. After a refusal, the page can
// also set data-wvp-verdict on the token field and fire wvp-verdict. See the listener below.
//
// What counts as the user. Measured on Chrome 157: Chrome marks blur() and focus() from a script as trusted, marks
// execCommand's input as trusted, and marks the change after checkbox.click() as trusted. So e.isTrusted alone on those proves nothing.
//  - Text: a value counts only if every edit was a trusted input that matches a trusted keydown of that very key, a trusted paste of
//    that very text, or a trusted IME session, and the result is exactly the old value with that one edit. Anything else taints the
//    field until it's emptied.
//  - Sign in: only a trusted click on button[data-wvp-signin], or a trusted Enter in the field. A script's click() stays untrusted.
//  - Verify: first use of a name on a site asks first, in a bubble this script draws. Only a trusted click on its Verify button goes on.
//    The button sits in a closed shadow root, so a page has nothing to call click() on. Not now sends nothing.
//  - Leaving the field: can open the bubble, and that's all. It's never a gesture, because a script's blur() is trusted too.
//  - Switch: only a trusted click, and it only locks the field.
(() => {
  // data-wvp-name and data-wvp-token are the hooks, so a page can say autocomplete="off". The autocomplete tokens are the old form, still read for pages that have them.
  const FIELD = 'input[data-wvp-name],input[autocomplete="wvp"]', SWITCH = 'input[type="checkbox"][data-wvp-anonymous]', TOKEN = 'input[data-wvp-token],input[autocomplete="wvp-token"]', SIGNIN = "button[data-wvp-signin]";
  const is = (t, sel) => t instanceof HTMLInputElement && t.matches(sel);
  const fields = new WeakMap();
  const track = (f) => { let s = fields.get(f); if (!s) fields.set(f, s = { tracked: "", tainted: false, key: null, paste: null, ime: false, done: null, dismissed: null }); return s; };
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
  // The field holds what the user typed, and nothing a script put there.
  const typedOk = (f) => { const s = track(f); return !s.tainted && f.value === s.tracked; };
  const inputOk = (e, s) => {
    if (s.ime) return true;
    if (s.paste !== null) return e.inputType === "insertFromPaste" && isSplice(s.tracked, e.target.value, s.paste);
    if (s.key === null) return false;
    if (e.inputType === "insertText") return e.data === s.key && isSplice(s.tracked, e.target.value, e.data);
    if (e.inputType.startsWith("delete")) return isSplice(s.tracked, e.target.value, "");
    return false;
  };

  window.addEventListener("keydown", (e) => {
    if (e.isTrusted && e.key === "Escape" && bubble) { track(bubble.f).dismissed = bubble.typed; closeBubble(); }
    if (!e.isTrusted || !is(e.target, FIELD)) return;
    const s = track(e.target);
    s.key = e.key;
    // Enter is the same action as Sign in. Don't let the form go before the token is in.
    if (e.key === "Enter") { e.preventDefault(); signIn(e.target.form); }
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
    if (bubble?.f === e.target) closeBubble();
    if (e.isTrusted) line(e.target, ""); // The user is on it. Whatever the line said is old now.
  }, true);
  // Leaving the field may ask the question, on a first use. It never signs in. See the top of this file.
  window.addEventListener("blur", (e) => {
    const f = e.target;
    if (!e.isTrusted || !is(f, FIELD)) return;
    // The whole window lost focus, say to another app. The field is still the active element. That's not leaving it.
    if (document.activeElement === f || !document.hasFocus()) return;
    const tok = tokenOf(f), s = track(f);
    if (!tok || f.readOnly || working.has(tok) || !f.value || !typedOk(f) || s.dismissed === f.value || s.done === doneKey(f)) return;
    offer(f, { leaving: true });
  }, true);
  window.addEventListener("click", (e) => {
    if (!e.isTrusted) return;
    if (is(e.target, SWITCH)) return flip(e.target);
    // Only a real click. A script's click() on this button stays untrusted, and ends here.
    const btn = e.target.closest?.(SIGNIN);
    if (!btn?.form) return;
    e.preventDefault();
    signIn(btn.form, btn);
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
    tok.form?.querySelector(SIGNIN)?.removeAttribute("disabled");
    if (ok && h && h.form.isConnected) h.form.requestSubmit(h.submitter?.isConnected ? h.submitter : undefined);
  };
  function start(job) {
    job.gen = ++gen;
    waiting = null;
    asking++;
    closeBubble();
    working.add(job.tok);
    line(job.tok, "");
    job.tok.form?.querySelector(SIGNIN)?.setAttribute("disabled", "");
    clearToken(job.tok);
    setState(job.tok, "working");
    queue = queue.then(() => run(job)).catch((e) => fail(job, plain(e)));
  }
  // The one way in: a real click on Sign in, or Enter in the field. Mode is whatever the switch says now.
  function signIn(form, btn) {
    const tok = form?.querySelector(TOKEN), sw = form?.querySelector(SWITCH), f = form?.querySelector(FIELD);
    if (!tok || working.has(tok)) return;
    // A first real press says we're here, so a page with no extension can say so. A page could already see the bubble's element.
    if (!tok.hasAttribute("data-wvp-state")) setState(tok, "idle");
    // Anonymous shows no name, so there's nothing to ask about.
    if (sw?.checked) { start({ mode: "anon", tok, field: f, sw }); holdSubmit(tok, btn); } else if (f) named(f, btn);
  }
  // A real submit button on a plain form: send the form once the token is in.
  const holdSubmit = (tok, btn) => { if (btn?.type === "submit" && working.has(tok)) heldSubmit.set(tok, { form: btn.form, submitter: btn }); };
  function named(f, btn) {
    const tok = tokenOf(f);
    if (!tok || f.readOnly) return;
    const s = track(f);
    if (f.value === "") return line(f, "Type your ENS name first.");
    if (!typedOk(f)) return refuseFilled(f);
    if (s.done === doneKey(f)) return;
    offer(f, { btn });
  }
  // A value we didn't see typed gets no proof. A page or the browser may have put it there, so this blames neither. Only a real press lands
  // here. The field goes empty, focused, one step from fixing it. An empty field carries nothing forged, so tracking starts over.
  const refuseFilled = (f) => {
    const s = track(f);
    f.value = "";
    f.dispatchEvent(new Event("input", { bubbles: true })); // So the page's own state follows. It lands in our listener above as untrusted, hence the reset after.
    Object.assign(s, { tracked: "", tainted: false, key: null, paste: null, ime: false, done: null, dismissed: null });
    f.focus();
    setState(tokenOf(f), "none");
    line(f, "Type your name by hand to sign in.");
  };
  // Asks the service worker where this site stands, then one of: nothing, the bubble, or the login. The worker decides, and checks again in prove.
  // With no gesture behind it (leaving), it can only open the bubble. With one (Sign in, Enter), a site already verified goes straight in.
  let asking = 0;
  const statusOf = (typed) => { const p = queue.then(() => ask("siteStatus", { typed })); queue = p.catch(() => {}); return p; };
  async function offer(f, { leaving = false, btn } = {}) {
    // Already showing. Sign in right after leaving the field lands here: one question, not two.
    if (bubble?.host.isConnected && bubble.f === f && bubble.typed === f.value) { bubble.btn = btn ?? bubble.btn; return; }
    const tok = tokenOf(f), typed = f.value, mine = ++asking;
    let st;
    try { st = await statusOf(typed); }
    catch (e) { if (!leaving && mine === asking) line(f, plain(e)); return; }
    // The user or the page moved on while we asked.
    if (mine !== asking || f.value !== typed || !typedOk(f) || f.readOnly || working.has(tok)) return;
    if (leaving) {
      // Quiet unless it's a question worth asking: a name, here for the first time.
      if (st.valid && st.kind === "name" && !st.mismatch && !st.verified) showBubble(f, typed, st, btn);
      return;
    }
    if (!st.valid || st.mismatch) { clearToken(tok); setState(tok, "none"); line(f, WHY[st.valid ? "no_match" : "invalid"]); return; }
    if (!st.verified) return showBubble(f, typed, st, btn);
    start({ mode: "name", tok, field: f, typed });
    holdSubmit(tok, btn);
  }
  function flip(sw) {
    const tok = tokenOf(sw), f = sw.form?.querySelector(FIELD);
    if (!tok) return;
    asking++;
    closeBubble();
    if (f) f.readOnly = sw.checked;
    // Flipping starts nothing. It only drops a login that was running or a token made for the other mode.
    if (!working.has(tok) && !tok.value) return;
    gen++; waiting = null;
    finish(tok, false);
    clearToken(tok);
    if (f) track(f).done = null;
    setState(tok, "idle");
  }
  // The site's answer only ever reaches the page, so the page has to pass it on. Only a not_owner, once, right after a token we made from a
  // real click. A lying page can only make the holder approve again, which needs a wallet signature. In the queue, so a Sign in right
  // after this goes to enrollment and not to the old approval.
  const delivered = new WeakMap();
  window.addEventListener("wvp-verdict", (e) => {
    const tok = e.target, typed = is(tok, TOKEN) ? delivered.get(tok) : undefined;
    if (typed === undefined || tok.getAttribute("data-wvp-verdict") !== "not_owner") return;
    delivered.delete(tok);
    queue = queue.then(() => ask("siteRefused", { reason: "not_owner", typed })).then((r) => {
      if (r.cleared) line(tok, "This browser forgot that approval. Sign in to approve the new wallet.");
    }).catch(() => {});
  }, true);
  const fail = (job, msg) => { if (job.gen !== gen) return; finish(job.tok, false); setState(job.tok, "none"); line(job.tok, msg); };

  const ask = (method, args, onProgress) => new Promise((ok, no) => {
    let answered = false, port;
    // The extension was reloaded and this tab wasn't. This script is cut off from it for good.
    try { port = chrome.runtime.connect({ name: "wvp" }); } catch { return no(Object.assign(new Error("reloaded"), { code: "extension_reloaded" })); }
    port.onMessage.addListener((m) => { if (m.progress) return onProgress?.(m.progress); answered = true; port.disconnect(); if (m.err) no(Object.assign(new Error(m.err.message), { code: m.err.code })); else ok(m.ok); });
    port.onDisconnect.addListener(() => { if (!answered) no(Object.assign(new Error("restarted"), { code: "extension_restarted" })); });
    port.postMessage({ method, args });
  });

  async function run(job) {
    if (job.gen !== gen) return;
    // getAttribute, like Chrome's EVP. A script setting el.nonce alone doesn't count.
    const nonce = job.tok.getAttribute("nonce") ?? "";
    let r;
    try { r = await ask("prove", { mode: job.mode, typed: job.typed ?? null, nonce, confirmed: !!job.confirmed }, (text) => line(job.tok, text)); }
    catch (e) {
      // The approval or the site's standing changed since we asked. Back to the question. Not awaited: offer waits for this queue.
      if (e.code === "needs_confirm" && job.gen === gen) { finish(job.tok, false); setState(job.tok, "none"); offer(job.field); return; }
      return fail(job, plain(e));
    }
    if (job.gen !== gen) return;
    if (r.enroll) { waiting = job; line(job.tok, "Approve in the new window. This continues by itself."); return; }
    // The page may have moved things while we proved. The proof is only for what was read at the start.
    const stillAnon = job.mode === "anon" ? job.sw.checked : job.field.value === job.typed;
    if (!job.tok.isConnected || job.tok.getAttribute("nonce") !== nonce || !stillAnon) return fail(job, "The page changed the form during sign-in. Not signed in.");
    job.tok.value = r.token;
    if (job.field && job.mode === "name") { track(job.field).done = doneKey(job.field); delivered.set(job.tok, job.typed); }
    setState(job.tok, "done");
    job.tok.dispatchEvent(new Event("input", { bubbles: true }));
    job.tok.dispatchEvent(new Event("change", { bubbles: true }));
    finish(job.tok, true);
  }
  const WHY = {
    no_match: "This browser is approved for a different name. Not signed in.",
    invalid: "That isn't an ENS name.",
    bad_nonce: "This site's sign-in form is broken. Not signed in.",
    busy: "Another sign-in is running. Try again in a moment.",
    no_activation: "That didn't come from a real click or key press.",
    extension_reloaded: "The WVP extension was reloaded. Reload this page.",
    extension_restarted: "Your browser's sign-in restarted. Try again.",
    bad_method: "Your extension is out of date. Reload it and this page.", // This script and the worker come from different builds.
    bad_request: "Your extension is out of date. Reload it and this page.",
  };
  // What may reach the status line: our own sentences. not_ready's text is written in the worker for this line. Anything else, an internal word or a thrown error's text, stays out.
  const plain = (e) => WHY[e?.code] ?? (e?.code === "not_ready" ? e.message : "Something went wrong with sign-in. Reload this page and try again.");
  chrome.runtime.onMessage.addListener((m, sender) => {
    if (sender.id !== chrome.runtime.id || m?.to !== "wvp-login" || !waiting) return;
    const job = waiting;
    waiting = null;
    if (m.kind === "resume") start(job);
    if (m.kind === "enroll-closed") fail(job, "Approval closed. Not signed in.");
  });

  // ---- the question, on a first use: a bubble hanging from the field. Drawn here in the page, so a page can cover it or draw a look-alike. A shipped
  // browser would draw this itself. Closed shadow root in the top layer. The host's style is inline and !important, so a stylesheet can't restyle or hide it,
  // and if a script edits the host, the bubble closes. Verify counts only 500 ms after it appears, so a click aimed at something else can't land on it. ----
  const FONT = "system-ui,-apple-system,sans-serif";
  const BUBBLE = `<style>
*{box-sizing:border-box}
.b{position:relative;width:min(400px,calc(100vw - 16px));background:#1f1f1f;color:#e3e3e3;border-radius:10px;padding:16px;font:13px/18px ${FONT};box-shadow:0 6px 24px #0000006b;user-select:none;text-align:left;cursor:default;animation:in .12s ease-out}
.a{position:absolute;top:-6px;width:14px;height:14px;background:#1f1f1f;border-radius:2px 0 0;transform:rotate(45deg)}
.a[hidden]{display:none}
h2{display:flex;align-items:center;gap:10px;margin:0 0 8px;font:500 14px/20px ${FONT};color:#e3e3e3}
svg{flex:none;width:20px;height:20px}
p{margin:0;color:#c7c7c7;overflow-wrap:anywhere}
.r{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
button{height:36px;padding:0 16px;border:0;border-radius:18px;font:500 13px/20px ${FONT};cursor:pointer}
button:hover{filter:brightness(1.1)}
button:focus-visible{outline:2px solid #a8c7fa;outline-offset:2px}
.n{background:#1b4a7c;color:#d3e3fd}
.v{background:#a8c7fa;color:#062e6f}
@keyframes in{from{opacity:0;transform:translateY(-3px)}}
@media (prefers-reduced-motion:reduce){.b{animation:none}}
</style><div class="b" role="dialog" aria-labelledby="h"><i class="a"></i><h2><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4.5" width="16" height="11" rx="2.5"/><path d="M6.6 10.1l2.3 2.3 4.5-4.8"/></svg><span id="h"></span></h2><p></p><div class="r"><button class="n" type="button">Not now</button><button class="v" type="button">Verify</button></div></div>`;
  let bubble = null;
  function closeBubble() { const b = bubble; bubble = null; b?.close(); }
  function showBubble(f, typed, st, btn) {
    closeBubble();
    const host = document.createElement("div"), root = host.attachShadow({ mode: "closed" });
    root.innerHTML = BUBBLE;
    root.querySelector("#h").textContent = `Verify this ${st.kind === "name" ? "name" : "address"} automatically?`;
    root.querySelector("p").textContent = `While this browser is approved, ${st.claim} can be confirmed on supported sites so you don't have to open your wallet`;
    const box = root.querySelector(".b"), arrow = root.querySelector(".a"), notNow = root.querySelector(".n"), verify = root.querySelector(".v");
    let style = "";
    const put = (left, top) => { host.style.cssText = `all:initial!important;display:block!important;position:fixed!important;left:${left}px!important;top:${top}px!important;z-index:2147483647!important`; style = host.getAttribute("style"); };
    const place = () => {
      const r = f.getBoundingClientRect();
      if (!f.isConnected || !r.width) return closeBubble();
      const w = box.offsetWidth, h = box.offsetHeight, vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
      const tip = r.left + Math.min(r.width / 2, 72), under = r.bottom + 10;
      const left = Math.round(Math.max(8, Math.min(tip - 32, vw - w - 8))), top = Math.round(Math.max(8, Math.min(under, vh - h - 8)));
      arrow.style.left = `${Math.round(Math.max(12, Math.min(tip - left - 7, w - 26)))}px`;
      arrow.hidden = top !== Math.round(under);
      put(left, top);
    };
    const watch = new MutationObserver(() => { if (host.getAttribute("style") !== style || host.getAttribute("popover") !== "manual") closeBubble(); });
    // A real press anywhere else closes it, like Not now. Sign in stays out of this: it goes to this same bubble, so it shouldn't blink.
    const outside = (e) => {
      const path = e.composedPath();
      if (!e.isTrusted || path.includes(host) || path.includes(f) || e.target.closest?.(SIGNIN)) return;
      track(f).dismissed = typed;
      closeBubble();
    };
    bubble = { host, f, typed, btn, close() {
      watch.disconnect();
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      window.removeEventListener("pointerdown", outside, true);
      host.remove();
    } };
    put(0, 0);
    host.setAttribute("popover", "manual");
    document.documentElement.append(host);
    try { host.showPopover(); } catch {} // No top layer, then. It's still fixed and on top of the page's normal content.
    place();
    if (bubble?.host !== host) return;
    watch.observe(host, { attributes: true });
    window.addEventListener("scroll", place, { capture: true, passive: true });
    window.addEventListener("resize", place);
    window.addEventListener("pointerdown", outside, true);
    const shownAt = performance.now();
    notNow.addEventListener("click", (e) => {
      if (!e.isTrusted || e.target !== notNow || bubble?.host !== host) return;
      track(f).dismissed = typed; // Leaving the field won't ask again about this value. Sign in or Enter still will.
      closeBubble();
    });
    verify.addEventListener("click", (e) => {
      if (!e.isTrusted || e.target !== verify || bubble?.host !== host || performance.now() - shownAt < 500) return;
      const tok = tokenOf(f), submitter = bubble.btn;
      closeBubble();
      if (!tok || f.readOnly || working.has(tok)) return;
      if (f.value !== typed || !typedOk(f)) return refuseFilled(f);
      start({ mode: "name", tok, field: f, typed, confirmed: true });
      holdSubmit(tok, submitter);
    });
  }

  // ---- one line in the site's form, for what the page must not learn. The site gives the place: div[data-wvp-status]. No slot, no line.
  // Closed shadow root, so page script can't read it. The small mark says this line is the browser's voice, not the site's. Fixed height and font: a page can't measure a message, and a page font can't leak its
  // characters. It's not a trust surface. A page can hide this or draw a look-alike. The toolbar popup holds what's true. ----
  const slots = new WeakMap();
  function line(el, text) {
    const host = el.form?.querySelector("[data-wvp-status]");
    if (!host) return;
    let box = slots.get(host);
    if (box === undefined) {
      box = null;
      try {
        const root = host.attachShadow({ mode: "closed" });
        root.innerHTML = `<style>div{display:flex;gap:6px;align-items:flex-start;contain:size;height:2.8em;width:100%;overflow:hidden;user-select:none;color:inherit;opacity:.72;font:13px/1.4 system-ui,sans-serif}svg{flex:none;width:16px;height:16px;margin-top:1px}svg[hidden]{display:none}</style><div role="status"><svg hidden viewBox="0 0 16 16" fill="none" aria-hidden="true"><rect x="1.5" y="3" width="13" height="10" rx="2.5" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="8" r="1.7" fill="currentColor"/></svg><span></span></div>`;
        box = { text: root.querySelector("span"), mark: root.querySelector("svg") };
      } catch {} // The page got there first. State only, then.
      slots.set(host, box);
    }
    if (box) { box.text.textContent = text; box.mark.toggleAttribute("hidden", !text); }
  }
})();
