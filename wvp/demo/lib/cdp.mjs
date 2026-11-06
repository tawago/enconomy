// Real Chrome over a CDP pipe, no debugging port at all. Node stdlib only. Extensions.loadUnpacked needs the pipe.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const CHROME = process.env.WVP_CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export const newProfile = () => mkdtempSync(join(tmpdir(), "wvp-chrome-profile-"));
export const dropProfile = (dir) => rmSync(dir, { recursive: true, force: true });

export async function launch({ profile, headless = true, stock = false, extra = [] }) {
  // stock: leaves out the flags that stop Chrome from slowing background work, so priority is what a user would get.
  const tune = stock ? [] : ["--disable-sync", "--disable-background-networking", "--disable-renderer-backgrounding", "--disable-background-timer-throttling"];
  const args = [`--user-data-dir=${profile}`, "--remote-debugging-pipe", "--enable-unsafe-extension-debugging", "--host-resolver-rules=MAP *.test 127.0.0.1", "--no-first-run", "--no-default-browser-check", ...tune, "--window-size=1100,800", ...extra, "about:blank"];
  if (headless) args.unshift("--headless=new");
  const p = spawn(CHROME, args, { stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] });
  let id = 0, buf = "", dead = null;
  const pend = new Map(), listeners = new Set();
  const die = (why) => { if (dead) return; dead = why; for (const { reject } of pend.values()) reject(new Error(`chrome gone: ${why}`)); pend.clear(); };
  p.on("exit", (c, s) => die(`exit ${c} ${s}`));
  p.stdio[4].setEncoding("utf8");
  p.stdio[4].on("data", (d) => {
    buf += d; let i;
    while ((i = buf.indexOf("\0")) >= 0) {
      const m = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
      if (m.id && pend.has(m.id)) { const q = pend.get(m.id); pend.delete(m.id); if (m.error) q.reject(new Error(`${q.method}: ${JSON.stringify(m.error)}`)); else q.resolve(m.result); }
      else if (m.method) for (const l of listeners) l(m);
    }
  });
  p.stdio[3].on("error", () => {});
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    if (dead) return reject(new Error(`chrome gone: ${dead}`));
    const i = ++id; pend.set(i, { resolve, reject, method });
    p.stdio[3].write(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }) + "\0");
  });
  const on = (f) => { listeners.add(f); return () => listeners.delete(f); };
  const version = await send("Browser.getVersion");
  await send("Target.setDiscoverTargets", { discover: true });

  async function attach(targetId) {
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    const s = (m, a) => send(m, a, sessionId);
    const evaluate = async (expression, { timeoutMs = 400000 } = {}) => {
      let to;
      const r = await Promise.race([
        s("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }),
        new Promise((_, j) => { to = setTimeout(() => j(new Error(`evaluate timed out after ${timeoutMs} ms: ${expression.slice(0, 80)}`)), timeoutMs); }),
      ]);
      clearTimeout(to);
      if (r.exceptionDetails) { const e = new Error(r.exceptionDetails.exception?.description ?? JSON.stringify(r.exceptionDetails)); throw e; }
      return r.result.value;
    };
    return { sessionId, targetId, send: s, evaluate };
  }
  async function newTab(url, { init = [], bindings = {} } = {}) {
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const t = await attach(targetId);
    await t.send("Page.enable"); await t.send("Runtime.enable"); await t.send("Inspector.enable").catch(() => {});
    for (const name of Object.keys(bindings)) await t.send("Runtime.addBinding", { name });
    on((m) => { if (m.sessionId === t.sessionId && m.method === "Runtime.bindingCalled" && bindings[m.params.name]) bindings[m.params.name](m.params.payload); });
    for (const source of init) await t.send("Page.addScriptToEvaluateOnNewDocument", { source });
    const loaded = new Promise((ok) => { const off = on((m) => { if (m.sessionId === t.sessionId && m.method === "Page.loadEventFired") { off(); ok(); } }); });
    await t.send("Page.navigate", { url });
    await loaded;
    return t;
  }
  const targets = async () => (await send("Target.getTargets")).targetInfos;
  async function close() {
    p.kill("SIGTERM");
    for (let i = 0; i < 30 && !dead; i++) await sleep(200);
    try { p.kill("SIGKILL"); } catch {}
    await sleep(300);
  }
  // Runs f once for every tab whose URL starts with prefix, including tabs the extension opens. The script goes in after the page
  // starts, so nothing here pauses a new target. Pausing would need auto-attach, and that keeps the service worker awake.
  function watchTabs(prefix, f) {
    const seen = new Set();
    return on(async (m) => {
      if (m.method !== "Target.targetCreated" && m.method !== "Target.targetInfoChanged") return;
      const i = m.params.targetInfo;
      if (i.type !== "page" || !i.url.startsWith(prefix) || seen.has(i.targetId)) return;
      seen.add(i.targetId);
      const t = await attach(i.targetId);
      await t.send("Page.enable"); await t.send("Runtime.enable");
      await f(t, i);
    });
  }
  return { p, send, on, attach, newTab, watchTabs, targets, close, version, isDead: () => dead };
}
