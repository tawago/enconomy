// Hands-on demo: opens a visible Chrome on a temp profile with the extension loaded. You type everything.
// FAKE parts, shown on screen: the wallet is a fresh throwaway key with a prompt drawn by this script, and ENS is a local table.
// Everything stays on 127.0.0.1. Quit Chrome to stop; servers and the profile are cleaned up.
// The hand-run steps printed below follow the Verify bubble. --smoke and --smoke-repoint predate it: they never click Verify, so they stop at the bubble and fail.
// --smoke: a script plays you once: a script click that must do nothing, named on Blobzon, anonymous on BlobChannel. Then everything quits.
// --repoint: you play the repoint story, with no issuer and no prover. The fake wallet has two throwaway keys.
// --smoke-repoint: a script plays that story once: approve with wallet A, log in, repoint the LOCAL TABLE to wallet B, not_owner, approve with wallet B, log in. Then a typed address gets name_only, a script's click is tried, and one more real login runs with no wallet.
// --ens deployment --deployment FILE --name NAME --wallet-a-key FILE, with --repoint or --smoke-repoint: the same story on our own ENS deployment on devnet 1337.
//   Sites read the chain at each login. Wallet A signs with the key in that file, read now and handed to Chrome in memory. Wallet B is a new throwaway key.
//   The repoint is the cold-key transaction, from repoint.mjs beside the deployment file. The wallet is still FAKE.
// --wallet-setup [--profile DIR]: opens Chrome on a dedicated profile at Rabby's store page. You install Rabby and make throwaway accounts by hand. This script never sees a key.
// --repoint --real-wallet --ens deployment --deployment FILE --name NAME [--profile DIR]: the chain story with your real wallet in that profile. Nothing fake is injected. You do every step.
//   The profile stays. Only WVP's own data and the demo sites' data are wiped, at each start.
import { spawn, execFileSync } from "node:child_process";
import { readFileSync, existsSync, readlinkSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { generatePrivateKey, privateKeyToAccount } from "viem/accounts";
import { launch, newProfile, dropProfile, sleep, CHROME } from "./lib/cdp.mjs";
import { chainLookup } from "../lib/ens-lookup.mjs";

const ROOT = new URL("..", import.meta.url).pathname;
const EXT = join(ROOT, "extension/build/extension");
// WVP_COMPONENT: the Chromium patch loads the extension itself, from beside the binary. Set WVP_CHROME to that binary too.
const COMPONENT = !!process.env.WVP_COMPONENT;
const SMOKE = process.argv.includes("--smoke"), SMOKE_REPOINT = process.argv.includes("--smoke-repoint");
const REPOINT = SMOKE_REPOINT || process.argv.includes("--repoint");
const APPROVE = "http://enroll.test:8806", A = "http://blobzon.test:8802", B = "http://blobchannel.test:8803";
const opt = (n) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? undefined : process.argv[i + 1]; };
const refuse = (why) => { console.error(why); process.exit(2); };

// The real wallet lives in this profile, so it's never the temp one and it's never removed.
const SETUP = process.argv.includes("--wallet-setup"), REAL = process.argv.includes("--real-wallet");
const RABBY_ID = "acmacodkjbdgmoleebolmdjonilkdbch", RABBY_STORE = `https://chromewebstore.google.com/detail/rabby-wallet/${RABBY_ID}`;
const PROFILE = resolve(opt("profile") ?? join(homedir(), ".wvp-demo-chrome"));
if (SETUP || REAL) {
  const normal = join(homedir(), "Library/Application Support/Google/Chrome");
  if (PROFILE === normal || PROFILE.startsWith(normal + "/")) refuse("--profile: that's your normal Chrome profile. Pick another folder.");
  try {
    const pid = Number(readlinkSync(join(PROFILE, "SingletonLock")).split("-").pop());
    process.kill(pid, 0);
    refuse(`Chrome is already open on ${PROFILE}. Quit it first.`);
  } catch (e) { if (e.code !== "ENOENT" && e.code !== "ESRCH") throw e; }
}
if (SETUP) {
  console.log(`
Setting up a separate Chrome just for this demo. Profile: ${PROFILE}
Do this by hand in the window that opens. This script doesn't touch your wallet or see its keys.
  1. Click Add to Chrome, and add Rabby Wallet.
  2. Open Rabby. Choose to CREATE A NEW wallet, set a password, and make two accounts.
  3. Use throwaway accounts only. They need no funds. NEVER import a seed phrase or key that holds real money.
  4. Note both addresses, and quit Chrome. Quitting ends this command.
Then run the demo:
  node demo/try-it.mjs --repoint --real-wallet --ens deployment --deployment <deployment.json> --name probe.eth${opt("profile") ? ` --profile ${PROFILE}` : ""}`);
  const chrome = spawn(CHROME, [`--user-data-dir=${PROFILE}`, "--no-first-run", "--no-default-browser-check", RABBY_STORE], { stdio: "ignore" });
  await new Promise((ok) => chrome.on("exit", ok));
  process.exit(0);
}
if (!existsSync(join(EXT, "sw.js")) || !existsSync(join(ROOT, "extension/build/fake-wallet.js"))) execFileSync(join(ROOT, "extension/build.sh"), { stdio: "inherit" });
const CHAIN = opt("ens") === "deployment";
if (opt("ens") && !CHAIN) refuse("--ens: this demo takes only deployment");
let NAME = "alice.eth", keys = [generatePrivateKey(), generatePrivateKey()], deployment, repointScript;
if (REAL && (!CHAIN || SMOKE || SMOKE_REPOINT || !REPOINT)) refuse("--real-wallet needs --repoint and --ens deployment. A script can't play a real wallet.");
if (CHAIN) {
  if (!REPOINT || !opt("deployment") || !opt("name") || (!REAL && !opt("wallet-a-key"))) refuse(`--ens deployment needs --repoint or --smoke-repoint, and --deployment, --name${REAL ? "" : " and --wallet-a-key"}`);
  NAME = opt("name");
  deployment = resolve(opt("deployment"));
  repointScript = join(dirname(deployment), "repoint.mjs");
  if (!existsSync(repointScript)) refuse("No repoint.mjs beside the deployment file.");
  if (!REAL) {
    const hot = readFileSync(opt("wallet-a-key"), "utf8").trim();
    if (!/^0x[0-9a-fA-F]{64}$/.test(hot)) refuse("--wallet-a-key: the file doesn't hold a 0x private key.");
    keys = [hot, generatePrivateKey()];
  }
}
let [addr, addrB] = keys.map((k) => privateKeyToAccount(k).address);
let restoreCmd = CHAIN ? `node ${repointScript} ${NAME} ${addr}` : "";
if (CHAIN) {
  const { rpc, chainId, universalResolver } = JSON.parse(readFileSync(deployment, "utf8"));
  if (chainId !== 1337) refuse(`Deployment says chain ${chainId}. This mode is for devnet 1337 only.`);
  const look = chainLookup({ rpcUrl: rpc, chainId, universalResolver });
  const live = await look.client.getChainId();
  if (live !== 1337) refuse(`The RPC is on chain ${live}, not 1337.`);
  const now = await look.resolve(NAME);
  console.log(`read ${NAME} on chain ${live}: ${now}`);
  if (REAL) {
    // No wallet key here, so there's nothing to compare with. The sites read the chain anyway: --owner only fills a table they don't use.
    addr = now ?? "0x0000000000000000000000000000000000000000";
    restoreCmd = `node ${repointScript} ${NAME} ${now ?? "<address>"}`;
    console.log(`
${NAME} points at ${now ?? "nothing"}. Make sure that's the account active in Rabby.
If it isn't, point it at your Rabby account 1 now (cold key, real transaction on devnet 1337), then start this again:
  node ${repointScript} ${NAME} <rabby-account-1>`);
    if (!existsSync(join(PROFILE, "Default/Extensions", RABBY_ID))) console.log(`
Rabby isn't installed on ${PROFILE} yet. Quit, and run: node demo/try-it.mjs --wallet-setup${opt("profile") ? ` --profile ${PROFILE}` : ""}`);
  } else if (now?.toLowerCase() !== addr.toLowerCase()) refuse(`${NAME} doesn't point at Wallet A ${addr}. Restore it first:\n  ${restoreCmd}`);
}
const ENS_TEXT = CHAIN ? "ENS is our own deployment on devnet 1337, not real ENS." : "ENS is a local table.";

const servers = spawn(process.execPath, ["demo/servers.mjs", "--owner", addr, ...(REPOINT ? ["--no-issuer"] : []), ...(CHAIN ? ["--name", NAME, "--ens", "deployment", "--deployment", deployment] : [])], { cwd: ROOT, stdio: ["ignore", "pipe", "inherit"] });
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
    d.style = "position:fixed;inset:0;background:#1A1A1888;z-index:99999;display:grid;place-items:center;font:14px/1.4 system-ui,sans-serif";
    const b = document.createElement("div");
    b.style = "background:#F6F6F4;color:#1A1A18;padding:18px;border-radius:12px;width:min(560px,calc(100vw - 24px));max-height:calc(100vh - 24px);display:flex;flex-direction:column;box-sizing:border-box;border:1px solid #1A1A1833";
    const h = document.createElement("h3"); h.textContent = "Demo wallet (scripted): signature request"; h.style = "margin:0 0 4px;font-size:15px;font-weight:600";
    const n = document.createElement("div"); n.textContent = ${JSON.stringify(CHAIN ? "FAKE WALLET, drawn by the demo script. Wallet A is a key read from a file, Wallet B is a throwaway. No real wallet is involved. " + ENS_TEXT : "FAKE WALLET, drawn by the demo script. A throwaway key signs. No real wallet is involved.")}; n.style = "font-size:12px;color:#1A1A18AA;margin-bottom:10px";
    // The text scrolls inside a padded box, in whole 16 px lines, so the last visible line is never cut in half.
    const w = document.createElement("div"); w.style = "display:flex;min-height:68px;flex:0 1 auto;background:#1A1A1810;padding:10px;margin:0 0 12px;border-radius:8px";
    const p = document.createElement("pre"); p.textContent = text; p.style = "white-space:pre-wrap;word-break:normal;overflow-wrap:anywhere;font:11px/16px ui-monospace,Menlo,monospace;margin:0;width:100%;overflow:auto;max-height:256px;scrollbar-width:thin;scrollbar-color:#1A1A1844 transparent";
    w.append(p);
    const row = document.createElement("div"); row.style = "display:flex;justify-content:flex-end;gap:8px;flex:none";
    const x = document.createElement("button"); x.textContent = "Reject"; x.style = "font:600 13px system-ui,sans-serif;padding:9px 16px;background:none;color:#1A1A18;border:1px solid #1A1A1833;border-radius:8px;cursor:pointer";
    const y = document.createElement("button"); y.id = "fake-sign"; y.textContent = "Sign"; y.style = "font:600 13px system-ui,sans-serif;padding:9px 16px;background:#1A1A18;color:#F6F6F4;border:1px solid #1A1A18;border-radius:8px;cursor:pointer";
    y.onclick = () => { d.remove(); ok(); }; x.onclick = () => { d.remove(); no(new Error("rejected in fake wallet")); };
    row.append(x, y);
    b.append(h, n, w, row); d.append(b); document.documentElement.append(d);
  });
  const fromHex = (h) => new TextDecoder().decode(Uint8Array.from(h.slice(2).match(/../g).map((x) => parseInt(x, 16))));
  globalThis.ethereum.request = async (a) => { if (a.method === "personal_sign") await ask(fromHex(a.params[0])); return real(a); };
  const banner = () => {
    document.getElementById("fake-wallet-banner")?.remove();
    const s = document.createElement("div");
    s.id = "fake-wallet-banner";
    s.textContent = ${JSON.stringify(`Demo wallet (scripted): ${CHAIN ? "demo keys" : "throwaway keys"}. ${ENS_TEXT} Using: `)};
    s.style = "flex:none;background:#8888881A;color:inherit;padding:8px 24px 10px;font:12px/1.4 system-ui,sans-serif;border-bottom:1px solid #88888840";
    const pick = document.createElement("select");
    pick.id = "fake-wallet-pick";
    pick.style = "display:block;width:100%;margin-top:6px;appearance:none;color:inherit;background:#88888822 no-repeat right 10px center url(\\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23888' stroke-width='1.5'/%3E%3C/svg%3E\\");border:1px solid #88888855;border-radius:7px;padding:6px 26px 6px 10px;font:11px/1.3 ui-monospace,Menlo,monospace;outline:none";
    ${JSON.stringify([addr, addrB])}.forEach((a, i) => pick.add(new Option("Wallet " + "AB"[i] + " " + a, i)));
    pick.onchange = () => globalThis.ethereum.__use(Number(pick.value));
    s.append(pick);
    document.body.prepend(s);
  };
  if (document.body) banner(); else addEventListener("DOMContentLoaded", banner);
})();`;
const init = readFileSync(join(ROOT, "extension/build/fake-wallet.js"), "utf8") + `\n;__installTestWallet(${JSON.stringify(keys)});\n` + prompt;

const profile = REAL ? PROFILE : newProfile();
const br = await launch({ profile, headless: false, stock: true });
// A clean close in real mode: a plain kill can lose what was just written, and the wallet lives here.
const stop = async (code = 0) => { try { servers.kill("SIGINT"); } catch {} if (REAL) await br.send("Browser.close").catch(() => {}); await br.close().catch(() => {}); await sleep(500); if (REAL) console.log(`Point the name back where it was when this started:\n  ${restoreCmd}`); else dropProfile(profile); process.exit(code); };
process.on("SIGINT", () => stop()); process.on("SIGTERM", () => stop());
const { id } = COMPONENT ? { id: "bundled component" } : await br.send("Extensions.loadUnpacked", { path: EXT });

// The profile keeps everything between runs, so the first login would skip the wallet. Clear WVP and the demo sites by origin. Nothing else goes.
// clearDataForOrigin takes the extension's IndexedDB but not chrome.storage. A tab on the extension's own origin clears that, then says what's left.
// Not the service worker for this: right after a load it can vanish mid-call. Not "all" on the extension either: that takes the worker for good.
if (REAL) {
  const page = (await br.targets()).find((t) => t.type === "page");
  const p = await br.attach(page.targetId);
  await p.send("Storage.clearDataForOrigin", { origin: `chrome-extension://${id}`, storageTypes: "indexeddb" });
  for (const origin of [APPROVE, A, B]) await p.send("Storage.clearDataForOrigin", { origin, storageTypes: "all" });
  const { targetId } = await br.send("Target.createTarget", { url: `chrome-extension://${id}/config.json`, background: true });
  const s = await br.attach(targetId);
  let left;
  for (let i = 0; i < 25 && !left; i++) {
    left = await s.evaluate(`(async () => { await chrome.storage.local.clear(); await chrome.storage.session.clear(); return { dbs: (await indexedDB.databases()).map((d) => d.name), local: Object.keys(await chrome.storage.local.get(null)), session: Object.keys(await chrome.storage.session.get(null)) }; })()`, { timeoutMs: 2000 }).catch(() => null);
    if (!left) await sleep(200);
  }
  await br.send("Target.closeTarget", { targetId });
  if (!left) { console.error("Couldn't reach WVP's storage, so its data wasn't wiped. Stopping."); await stop(1); }
  await br.send("Target.detachFromTarget", { sessionId: p.sessionId });
  console.log(`wiped WVP and demo site data. WVP has left: ${JSON.stringify(left)}`);
  if (left.dbs.length || left.local.length || left.session.length) { console.error("WVP's data is still there. Stopping."); await stop(1); }
}

// The extension opens this tab, so the fake wallet goes in as it appears.
const enrollTabs = [];
if (!REAL) br.watchTabs(`${APPROVE}/enroll`, async (t) => {
  await t.send("Page.addScriptToEvaluateOnNewDocument", { source: init });
  await t.evaluate(init + ";0");
  enrollTabs.push(t);
});
// launch() starts Chrome on about:blank. That tab becomes the first site, so no blank tab sits in the strip.
let startTab;
for (let i = 0; i < 20 && !startTab; i++) {
  startTab = (await br.targets()).find((t) => t.type === "page" && t.url === "about:blank");
  if (!startTab) await sleep(100);
}
const tb = await br.newTab(`${B}/`, { targetId: startTab?.targetId });
const ta = await br.newTab(`${A}/`);
// If that tab showed up late, it's still blank. Close it.
for (const t of await br.targets()) if (t.type === "page" && t.url === "about:blank") await br.send("Target.closeTarget", { targetId: t.targetId }).catch(() => {});
await sleep(500);
const before = await ta.evaluate(`({ wvp: typeof window.wvp, form: !!document.querySelector('input[data-wvp-name]'), token: !!document.querySelector('input[autocomplete="wvp-token"]').getAttribute("nonce"), title: document.title })`);
await ta.send("Page.bringToFront");
console.log(`chrome ${br.version.product}  extension ${id}`);
console.log(`check ${JSON.stringify(before)}`);
if (REAL) console.log(`
Ready: the repoint story with your real wallet. Rabby is real, in its own Chrome profile. ENS is our own deployment on devnet 1337, not real ENS. No issuer, so no anonymous.
You do every step. This script never touches the wallet.
  1. Unlock Rabby. Make sure account 1 is active. ${NAME} must point at it.
  2. On Blobzon, type ${NAME}, then leave the field (Tab, or click elsewhere). A dark bubble opens under the field. Click Verify. A small approval window opens. Click Connect wallet.
     Clicking Sign in or pressing Enter first gets you the same bubble. Not now closes it and sends nothing.
  3. Approve in Rabby with account 1: connect, then sign. You land back on Blobzon, signed in.
  4. Sign out. In another terminal, send the real cold-key transaction:
       node ${repointScript} ${NAME} <rabby-account-2>
  5. Type ${NAME}, click Sign in. No bubble, this site is already verified. Refused: the site says the name points to a different wallet. It's the same browser and the same approval.
  6. SWITCH THE ACTIVE ACCOUNT IN RABBY to account 2. The approval page signs with whichever account Rabby gives it.
  7. Click Sign in again. The approval is gone, so the bubble is back. Click Verify, click Connect wallet in the small window, and approve in Rabby. You're in, as ${NAME}.
  8. Sign out, type ${NAME}, press Enter. No bubble, no wallet. Leaving the field does nothing here. You need Enter or Sign in.
Quit Chrome when done. That stops the servers. Your Rabby stays in the profile, and only WVP's data gets wiped next time.
To point the name back where it was when this started:
  ${restoreCmd}`);
else if (CHAIN) console.log(`
Ready: the repoint story on a chain. The wallet is FAKE, drawn by this script. ENS is our own deployment on devnet 1337, not real ENS. No issuer, so no anonymous.
  Wallet A: ${addr}  (${NAME} points here now, read from the chain. The key comes from the file you passed.)
  Wallet B: ${addrB}  (a new throwaway key, gone when this quits)
  1. On Blobzon, type ${NAME}, then leave the field (Tab, or click elsewhere). A dark bubble opens under the field. Click Verify. Clicking Sign in or pressing Enter first gets you the same bubble.
     In the small window, keep Wallet A, click Connect wallet, then Sign in the demo wallet box. You're in.
  2. Sign out. In another terminal, send the real cold-key transaction:
       node ${repointScript} ${NAME} ${addrB}
  3. Type ${NAME}, click Sign in. No bubble, this site is already verified. Refused: not_owner. It's the same browser and the same approval.
  4. Click Sign in again. The approval is gone, so the bubble is back. Click Verify. In the small window, pick Wallet B in the Demo wallet bar, and approve. You're in, as ${NAME}.
  5. Sign out, type ${NAME}, press Enter. No bubble, no wallet. Leaving the field does nothing here. You need Enter or Sign in.
  6. After you quit, Wallet B's key is gone. Point the name back:
       ${restoreCmd}
Quit Chrome when done. That stops everything.`);
else if (REPOINT) console.log(`
Ready: the repoint story. FAKE wallets, throwaway keys. ENS is a LOCAL TABLE. No issuer, so no anonymous.
  Wallet A: ${addr}  (alice.eth points here now)
  Wallet B: ${addrB}
  1. On Blobzon, type alice.eth, then leave the field (Tab, or click elsewhere). A dark bubble opens under the field. Click Verify. Clicking Sign in or pressing Enter first gets you the same bubble.
     In the small window, keep Wallet A, click Connect wallet, then Sign in the demo wallet box. You're in.
  2. In another terminal: node demo/repoint.mjs alice.eth ${addrB}
  3. Sign out. Type alice.eth, click Sign in. No bubble, this site is already verified. Refused: not_owner. It's the same browser and the same approval.
  4. Click Sign in again. The approval is gone, so the bubble is back. Click Verify. In the small window, pick Wallet B in the Demo wallet bar, and approve. You're in, as alice.eth.
  5. Sign out, type alice.eth, press Enter. No bubble, no wallet. Leaving the field does nothing here. You need Enter or Sign in.
  Typing the approved wallet's address and clicking Sign in gets name_only.
Quit Chrome when done. That stops everything.`);
else console.log(`
Ready. A script is not playing you now. Blobzon and BlobChannel are open.
  ENS name:  alice.eth        Address: ${addr}   (fake wallet, throwaway key. ENS is a local table.)
  1. On Blobzon, type alice.eth, then leave the field (Tab, or click elsewhere). A dark bubble opens under the field. Click Verify.
     Clicking Sign in or pressing Enter first gets you the same bubble. Not now closes it and sends nothing.
  2. A small window opens for the one signature. Click Connect wallet, then Sign in the demo wallet box.
  3. You land back on Blobzon, and it signs in by itself, almost at once.
  4. Sign out, type alice.eth, press Enter. No bubble, no wallet. Leaving the field does nothing here. You need Enter or Sign in.
  5. On BlobChannel, type alice.eth and leave the field. The bubble again, because it's a new site. Click Verify. No wallet this time.
  6. Sign out there, tick "Watch without showing a name" and click Sign in. No bubble, no wallet, no name shared. It waits if the background setup is still running.
  The puzzle icon in the toolbar has "WVP": who's approved, what sites saw, Remove approval. Pin it to see the badge.
Quit Chrome when done. That stops everything.`);

const rect = (t, sel) => t.evaluate(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
const click = async (t, sel) => { const r = await rect(t, sel); for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await t.send("Input.dispatchMouseEvent", { type, x: r.x, y: r.y, button: type === "mouseMoved" ? "none" : "left", clickCount: type === "mouseMoved" ? 0 : 1 }); };
const typeIn = async (t, sel, text) => { await click(t, sel); for (const c of text) { await t.send("Input.dispatchKeyEvent", { type: "keyDown", key: c, text: c }); await t.send("Input.dispatchKeyEvent", { type: "keyUp", key: c }); } };
const result = async (t) => {
  for (let i = 0; i < 2400; i++) { if (await t.evaluate("window.__result")) break; await sleep(100); }
  return t.evaluate(`({ accepted: window.__result?.accepted, name: window.__result?.name, address: window.__result?.address, kind: window.__result?.kind, mode: window.__result?.mode, reason: window.__result?.reason, lookup: window.__result?.lookup, totalMs: window.__result?.totalMs })`);
};

if (SMOKE_REPOINT) {
  const out = { before, walletA: addr, walletB: addrB };
  let code = 1;
  const say = (step, o) => { out[step] = o; console.log(`step ${step} ${JSON.stringify(o)}`); };
  // The wallet tab the extension opened, number n. Pick a wallet, approve, sign.
  const approve = async (n, wallet) => {
    for (let i = 0; i < 100 && enrollTabs.length <= n; i++) await sleep(100);
    if (enrollTabs.length <= n) throw new Error(`no enrollment tab ${n}`);
    const e = enrollTabs[n];
    await sleep(800);
    await e.evaluate(`(() => { const p = document.getElementById("fake-wallet-pick"); p.value = "${wallet}"; p.onchange(); })()`);
    await click(e, "#go");
    for (let i = 0; i < 100; i++) { if (await e.evaluate(`!!document.getElementById("fake-sign")`)) break; await sleep(100); }
    if (!out.walletText) say("walletText", await e.evaluate(`({ banner: document.getElementById("fake-wallet-banner").firstChild.textContent, box: [...document.querySelectorAll("#fake-wallet h3, #fake-wallet h3 + div")].map((x) => x.textContent) })`));
    await click(e, "#fake-sign");
  };
  const signOut = async () => {
    await click(ta, "#out");
    for (let i = 0; i < 100; i++) { await sleep(100); if (await ta.evaluate(`document.readyState === "complete" && !document.getElementById("out") && !document.getElementById("go").hidden`).catch(() => false)) break; }
    await sleep(300);
  };
  try {
    await ta.send("Page.bringToFront");
    await typeIn(ta, "#who", NAME);
    let t0 = Date.now();
    await click(ta, "#go");
    await approve(0, 0);
    say("loginWalletA", { ...(await result(ta)), wallMsFromClick: Date.now() - t0 }); // Wall time includes the script's own waits on the wallet tab.
    await signOut();
    if (CHAIN) console.log(`repoint: real cold-key transaction: node ${repointScript} ${NAME} ${addrB}`);
    say("repoint", execFileSync(process.execPath, [CHAIN ? repointScript : join(ROOT, "demo/repoint.mjs"), NAME, addrB], { encoding: "utf8" }).trim());
    await typeIn(ta, "#who", NAME);
    await click(ta, "#go");
    say("sameApprovalRefused", await result(ta));
    say("walletPromptsSoFar", enrollTabs.length);
    await ta.evaluate("window.__result = null");
    t0 = Date.now();
    await click(ta, "#go");
    await approve(1, 1);
    say("loginWalletB", { ...(await result(ta)), wallMsFromClick: Date.now() - t0 });
    await signOut();
    await typeIn(ta, "#who", addrB.toLowerCase());
    await click(ta, "#go");
    say("typedAddress", await result(ta));
    // A script's click on Sign in, with the good name typed for real and a good approval in place.
    await ta.send("Page.reload");
    for (let i = 0; i < 100; i++) { await sleep(100); if (await ta.evaluate(`document.readyState === "complete" && !!document.getElementById("go")`).catch(() => false)) break; }
    await sleep(300);
    await typeIn(ta, "#who", NAME);
    await ta.evaluate(`document.querySelector("[data-wvp-signin]").click()`);
    await sleep(2000);
    say("scriptClick", { newWalletTabs: enrollTabs.length - 2, state: await ta.evaluate(`document.getElementById("token").dataset.wvpState ?? null`), tokenFilled: await ta.evaluate(`!!document.getElementById("token").value`), result: await ta.evaluate("window.__result") });
    // The same field, now a real click. No wallet, and ENS is read again.
    t0 = Date.now();
    await click(ta, "#go");
    say("returningLogin", { ...(await result(ta)), wallMsFromClick: Date.now() - t0, walletTabs: enrollTabs.length });
    const { loginWalletA: a, sameApprovalRefused: no, loginWalletB: b, typedAddress: t } = out;
    code = a.accepted && a.name === NAME && a.address === addr && !no.accepted && no.reason === "not_owner" && out.walletPromptsSoFar === 1 && b.accepted && b.name === NAME && b.address === addrB && !t.accepted && t.reason === "name_only" && out.returningLogin.accepted && out.returningLogin.address === addrB && out.returningLogin.walletTabs === 2 ? 0 : 1;
  } catch (err) { out.err = String(err); }
  console.log(`smoke-repoint ${code ? "FAILED" : "PASSED"} ${JSON.stringify(out)}`);
  if (CHAIN) console.log(`${NAME} still points at the last repoint. Wallet A again: ${restoreCmd}`);
  await stop(code);
}
if (SMOKE) {
  const out = { before };
  let code = 1;
  try {
    await typeIn(ta, "#who", "alice.eth");
    // A script's click on Sign in, with a good name typed, must do nothing.
    await ta.evaluate(`document.querySelector("[data-wvp-signin]").click()`);
    await sleep(2000);
    out.scriptClick = { enrollTabs: enrollTabs.length, state: await ta.evaluate(`document.getElementById("token").dataset.wvpState ?? null`), result: await ta.evaluate("window.__result") };
    await click(ta, "#go");
    for (let i = 0; i < 100 && !enrollTabs.length; i++) await sleep(100);
    if (!enrollTabs.length) throw new Error("no enrollment tab");
    const e = enrollTabs[0];
    await e.send("Runtime.enable");
    await sleep(800);
    await click(e, "#go");
    for (let i = 0; i < 100; i++) { if (await e.evaluate(`!!document.getElementById("fake-sign")`)) break; await sleep(100); }
    out.promptShown = await e.evaluate(`document.getElementById("fake-wallet").textContent.includes("FAKE WALLET")`);
    await click(e, "#fake-sign");
    out.named = await result(ta);
    await tb.send("Page.bringToFront");
    await click(tb, "#anon");
    await click(tb, "#go");
    out.anonymous = await result(tb);
    out.walletTabs = enrollTabs.length;
    const quiet = !out.scriptClick.enrollTabs && !out.scriptClick.state && !out.scriptClick.result;
    code = quiet && out.promptShown && out.walletTabs === 1 && out.named.accepted && out.named.name === "alice.eth" && out.named.mode === "direct" && out.anonymous.accepted && out.anonymous.kind === "anonymous" ? 0 : 1;
  } catch (err) { out.err = String(err); }
  console.log(`smoke ${JSON.stringify(out)}`);
  await stop(code);
}
while (!br.isDead()) await sleep(1000);
await stop();
