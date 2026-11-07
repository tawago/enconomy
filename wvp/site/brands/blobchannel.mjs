// BlobChannel, a fictional video site. Quiet on purpose: a wordmark, the sign-in, and a few plain lines once you're in. Nothing plays.
export const title = "BlobChannel", kind = "video site", anonLabel = "Watch without showing a name";
export const favicon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="3" y="6" width="26" height="20" rx="5" fill="#4D6B5A"/></svg>`;

export const css = `
  :root { --bg: #FAFAF9; --ink: #1C1C1C; --dim: #6B6B6B; --accent: #4D6B5A; --error: #A63D2F; --rule: #E2E2E0; color-scheme: light; }
  body { min-height: 100vh; display: flex; flex-direction: column; background: var(--bg); color: var(--ink); font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 24px; }
  .brand { font-size: 18px; font-weight: 500; }
  .brand em { font-style: normal; color: var(--accent); }
  #account { display: flex; align-items: center; min-height: 32px; }
  .acct { display: none; }
  #out { font: inherit; font-size: 14px; color: var(--dim); background: none; border: 1px solid var(--rule); border-radius: 6px; padding: 4px 12px; cursor: pointer; }
  main { flex: 1; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .box { width: 100%; max-width: 340px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 18px; }
  #login { display: grid; gap: 10px; font-size: 13px; }
  #login .name { color: var(--dim); }
  .entry { display: grid; gap: 10px; }
  #who { font: inherit; font-size: 15px; color: var(--ink); background: #FFF; border: 1px solid #BDBDBB; border-radius: 6px; padding: 9px 40px 9px 11px; outline: none; }
  #who:focus { border-color: var(--accent); }
  #who::placeholder { color: #9A9A9A; }
  #go { font: inherit; font-size: 15px; font-weight: 500; color: #FFF; background: var(--accent); border: 0; border-radius: 6px; padding: 10px; cursor: pointer; }
  #anon { accent-color: var(--accent); width: 14px; height: 14px; margin: 0; }
  .share { color: var(--dim); opacity: 1; }
  #status { font-size: 13px; }
  .who { margin: 0; font-size: 18px; word-break: break-word; }
  .addr { display: block; margin-top: 2px; font: 12px ui-monospace, Menlo, monospace; color: var(--dim); }
  h2 { font-size: 13px; font-weight: 500; color: var(--dim); margin: 24px 0 6px; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { display: flex; justify-content: space-between; gap: 16px; padding: 7px 0; border-top: 1px solid var(--rule); font-size: 14px; }
  li span { color: var(--dim); white-space: nowrap; }
  .colophon { padding: 12px 24px 16px; font-size: 12px; color: var(--dim); text-align: center; }
`;

export const header = (account) => `<header class="top"><div class="brand">Blob<em>Channel</em></div>${account}</header>`;

export const signedOut = (form) => `<div class="box"><h1>Sign in to BlobChannel</h1>${form}</div>`;

const VIDEOS = [["Slow rivers, recorded at night", "41 min left"], ["I rebuilt a bus radio", "9 min left"], ["Forty years of one bakery", "46 min left"]];
export const signedIn = (u, esc) => `<div class="box">
  <p class="who">${u.name ? `Signed in as <b>${esc(u.name)}</b>` : "Signed in without a name"}</p>
  ${u.address ? `<code class="addr" title="${esc(u.address)}">${esc(u.short)}</code>` : ""}
  <h2>Keep watching</h2>
  <ul>${VIDEOS.map(([video, left]) => `<li>${video}<span>${left}</span></li>`).join("")}</ul>
</div>`;
