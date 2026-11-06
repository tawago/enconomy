// Hands-on demo: opens a visible Chrome on a temp profile with the extension loaded. You type everything.
// FAKE parts, shown on screen: the wallet is a fresh throwaway key with a prompt drawn by this script, and ENS is a local table.
// Everything stays on 127.0.0.1. Quit Chrome to stop; servers and the profile are cleaned up.
// --smoke: a script plays you once, through to a verified login, then everything quits. For checking this starts.
import { spawn, execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { launch, newProfile, dropProfile, sleep } from "./lib/cdp.mjs";

const ROOT = new URL("..", import.meta.url).pathname;
const EXT = join(ROOT, "extension/build/extension");
// WVP_COMPONENT: the Chromium patch loads the extension itself, from beside the binary. Set WVP_CHROME to that binary too.
const COMPONENT = !!process.env.WVP_COMPONENT;
const SMOKE = process.argv.includes("--smoke");
const ISSUER = "http://issuer.test:8801", A = "http://site-a.test:8802", B = "http://site-b.test:8803";
if (!existsSync(join(EXT, "sw.js")) || !existsSync(join(ROOT, "extension/build/fake-wallet.js"))) execFileSync(join(ROOT, "extension/build.sh"), { stdio: "inherit" });
const key = generatePrivateKey();
const addr = privateKeyToAccount(key).address;

const servers = spawn(process.execPath, ["demo/servers.mjs", "--owner", addr], { cwd: ROOT, stdio: ["ignore", "pipe", "inherit"] });
await new Promise((ok, no) => {
  servers.stdout.on("data", (d) => { if (String(d).startsWith("Ready") || String(d).includes("\nReady")) ok(); });
  servers.on("exit", (c) => no(new Error(`servers exited ${c}`)));
});
servers.removeAllListeners("exit");

// The prompt is drawn on the enrollment page by this script. A real wallet would be its own window. Labelled so nobody mistakes it.
const prompt = `
(() => {
  const real = globalThis.ethereum.request.bind(globalThis.ethereum);
  const ask = (text) => new Promise((ok, no) => {
    const d = document.createElement("div");
    d.id = "fake-wallet";
    d.style = "position:fixed;inset:0;background:#0009;z-index:99999;display:grid;place-items:center;font:15px system-ui";
    const b = document.createElement("div");
    b.style = "background:#fff;color:#111;padding:20px;border-radius:10px;width:560px;max-height:80vh;overflow:auto;border-top:6px solid #c00";
    const h = document.createElement("h3"); h.textContent = "FAKE WALLET: signature request"; h.style = "margin:0 0 4px;color:#c00";
    const n = document.createElement("div"); n.textContent = "Drawn by the demo script. A throwaway key signs. No real wallet is involved."; n.style = "font-size:13px;color:#555;margin-bottom:10px";
    const p = document.createElement("pre"); p.textContent = text; p.style = "white-space:pre-wrap;word-break:break-all;font-size:12px;background:#f3f3f3;padding:10px";
    const y = document.createElement("button"); y.id = "fake-sign"; y.textContent = "Sign"; y.style = "width:auto;font-size:15px;padding:8px 22px;margin-right:8px";
    const x = document.createElement("button"); x.textContent = "Reject"; x.style = "width:auto;font-size:15px;padding:8px 22px;background:#fff;color:#111;border:1px solid #bbb";
    y.onclick = () => { d.remove(); ok(); }; x.onclick = () => { d.remove(); no(new Error("rejected in fake wallet")); };
    b.append(h, n, p, y, x); d.append(b); document.documentElement.append(d);
  });
  const fromHex = (h) => new TextDecoder().decode(Uint8Array.from(h.slice(2).match(/../g).map((x) => parseInt(x, 16))));
  globalThis.ethereum.request = async (a) => { if (a.method === "personal_sign") await ask(fromHex(a.params[0])); return real(a); };
  const banner = () => {
    const s = document.createElement("div");
    s.textContent = "FAKE WALLET on this page: throwaway key ${addr}. ENS is a local table.";
    s.style = "position:fixed;top:0;left:0;right:0;background:#c00;color:#fff;padding:6px 10px;font:13px system-ui;text-align:center;z-index:9";
    document.body.prepend(s);
  };
  if (document.body) banner(); else addEventListener("DOMContentLoaded", banner);
})();`;
const init = readFileSync(join(ROOT, "extension/build/fake-wallet.js"), "utf8") + `\n;__installTestWallet(${JSON.stringify(key)});\n` + prompt;

const profile = newProfile();
const br = await launch({ profile, headless: false, stock: true });
const stop = async (code = 0) => { try { servers.kill("SIGINT"); } catch {} await br.close().catch(() => {}); await sleep(500); dropProfile(profile); process.exit(code); };
process.on("SIGINT", () => stop()); process.on("SIGTERM", () => stop());
const { id } = COMPONENT ? { id: "bundled component" } : await br.send("Extensions.loadUnpacked", { path: EXT });

// The extension opens this tab, so the fake wallet goes in as it appears.
const enrollTabs = [];
br.watchTabs(`${ISSUER}/enroll`, async (t) => {
  await t.send("Page.addScriptToEvaluateOnNewDocument", { source: init });
  await t.evaluate(init + ";0");
  enrollTabs.push(t);
});
const tb = await br.newTab(`${B}/`);
const ta = await br.newTab(`${A}/`);
await sleep(500);
const before = await ta.evaluate(`({ wvp: typeof window.wvp, form: !!document.querySelector('input[autocomplete="wvp"]'), token: !!document.querySelector('input[autocomplete="wvp-token"]').getAttribute("nonce"), title: document.title })`);
await ta.send("Page.bringToFront");
console.log(`chrome ${br.version.product}  extension ${id}`);
console.log(`check ${JSON.stringify(before)}`);
console.log(`
Ready. A script is not playing you now. Site A and Site B are open.
  ENS name:  alice.eth        Address: ${addr}   (fake wallet, throwaway key. ENS is a local table.)
  1. On Site A, type alice.eth and press Tab.
  2. A tab opens for the first signature. Click the button, then Sign in the FAKE WALLET box.
  3. You land back on Site A, and it verifies by itself.
  4. On Site B, flip Anonymous. Then Sign out and paste the address above. No wallet either time.
  The puzzle icon in the toolbar has "WVP": what's enrolled, proofs made, Revoke.
Quit Chrome when done. That stops everything.`);

if (SMOKE) {
  const rect = (t, sel) => t.evaluate(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
  const click = async (t, sel) => { const r = await rect(t, sel); for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await t.send("Input.dispatchMouseEvent", { type, x: r.x, y: r.y, button: type === "mouseMoved" ? "none" : "left", clickCount: type === "mouseMoved" ? 0 : 1 }); };
  const out = { before };
  let code = 1;
  try {
    await click(ta, "#who");
    for (const c of "alice.eth") { await ta.send("Input.dispatchKeyEvent", { type: "keyDown", key: c, text: c }); await ta.send("Input.dispatchKeyEvent", { type: "keyUp", key: c }); }
    await ta.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
    await ta.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
    for (let i = 0; i < 100 && !enrollTabs.length; i++) await sleep(100);
    if (!enrollTabs.length) throw new Error("no enrollment tab");
    const e = enrollTabs[0];
    await e.send("Runtime.enable");
    await sleep(800);
    await click(e, "#go");
    for (let i = 0; i < 100; i++) { if (await e.evaluate(`!!document.getElementById("fake-sign")`)) break; await sleep(100); }
    out.promptShown = await e.evaluate(`document.getElementById("fake-wallet").textContent.includes("FAKE WALLET")`);
    await click(e, "#fake-sign");
    for (let i = 0; i < 1800; i++) { if (await ta.evaluate("window.__result")) break; await sleep(100); }
    out.result = await ta.evaluate(`({ accepted: window.__result?.accepted, name: window.__result?.name, reason: window.__result?.reason, totalMs: window.__result?.totalMs })`);
    code = out.result.accepted && out.result.name === "alice.eth" && out.promptShown ? 0 : 1;
  } catch (err) { out.err = String(err); }
  console.log(`smoke ${JSON.stringify(out)}`);
  await stop(code);
}
while (!br.isDead()) await sleep(1000);
await stop();
