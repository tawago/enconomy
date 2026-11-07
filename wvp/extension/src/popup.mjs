// The extension's action popup: who's approved, what each site saw, and Remove approval.
const send = (m) => chrome.runtime.sendMessage({ to: "sw", ...m });
const $ = (id) => document.getElementById(id);
const short = (a) => `${a.slice(0, 6)}\u2026${a.slice(-4)}`;
const until = (s) => new Date(s * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const ago = (s) => {
  const d = Math.max(0, Math.floor(Date.now() / 1000) - s);
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return `${Math.floor(d / 86400)} d ago`;
};
const host = (o) => { try { return new URL(o).host; } catch { return o; } };
const el = (cls, text) => { const e = document.createElement("span"); e.className = cls; e.textContent = text; return e; };
async function draw() {
  const st = await send({ kind: "popup-status" });
  $("who").textContent = st.enrolled ? st.name : "No approval yet";
  $("addr").textContent = st.enrolled ? short(st.address) : "";
  $("addr").title = st.enrolled ? st.address : "";
  $("exp").textContent = !st.enrolled ? "Your wallet asks the first time you sign in." : `${st.expired ? "Approval ended" : "Approved until"} ${until(st.exp)}`;
  $("revoke").hidden = $("revokeWhy").hidden = !st.enrolled;
  $("rm").hidden = !st.enrolled;
  $("log").textContent = "";
  // Newest first. A run of the same site seeing the same thing is one row with a count.
  const rows = [];
  for (const p of st.proofs) {
    const last = rows.at(-1);
    if (last && last.origin === p.origin && last.revealed === p.revealed) last.count++; else rows.push({ ...p, count: 1 });
  }
  for (const p of rows) {
    const li = document.createElement("li");
    const saw = p.revealed ? p.revealed.replace(/0x[0-9a-fA-F]{40}/, short) : "a valid approval, nothing else";
    const where = el("host", host(p.origin));
    if (p.count > 1) where.append(el("times", `\u00d7${p.count}`));
    li.append(where, el("ago", ago(p.t)), el("saw", saw));
    $("log").append(li);
  }
  // The list scrolls with no bar, so end it on a whole row and say what's below.
  const SHOWN = 4, items = [...$("log").children];
  $("log").style.maxHeight = items.length > SHOWN ? `${items[SHOWN - 1].getBoundingClientRect().bottom - $("log").getBoundingClientRect().top}px` : "";
  $("more").hidden = items.length <= SHOWN;
  $("more").textContent = `Scroll for ${items.length - SHOWN} more`;
  $("none").hidden = st.proofs.length > 0;
  window.__ready = true;
}
$("revoke").addEventListener("click", async (e) => {
  if (!e.isTrusted) { window.__ignoredUntrusted = (window.__ignoredUntrusted ?? 0) + 1; return; }
  $("revoke").disabled = true;
  await send({ kind: "revoke" });
  $("revoke").disabled = false;
  await draw();
});
await draw();
