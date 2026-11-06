// The extension's action popup: what's enrolled, what was proved where, and Revoke.
const send = (m) => chrome.runtime.sendMessage({ to: "sw", ...m });
const $ = (id) => document.getElementById(id);
const when = (s) => new Date(s * 1000).toLocaleString();
async function draw() {
  const st = await send({ kind: "popup-status" });
  $("who").textContent = st.enrolled ? `${st.name}\n${st.address}` : "Not enrolled.";
  $("exp").textContent = st.enrolled ? `${st.expired ? "Expired" : "Good until"} ${when(st.exp)}` : "The next login takes you to enrollment.";
  $("revoke").hidden = !st.enrolled;
  $("log").textContent = "";
  for (const p of st.proofs) { const li = document.createElement("li"); li.textContent = `${p.origin}: ${p.revealed ?? "hidden"}, ${when(p.t)}`; $("log").append(li); }
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
