// Starts the issuer, key host and two sites, then waits. Doesn't start Chrome. Use it to try a real wallet with a throwaway account.
// Usage: node demo/servers.mjs --owner 0xYOUR_THROWAWAY_ADDRESS [--name alice.eth]
// The two sites hold verifying keys in memory, about 1.1 GiB each.
import { spawn } from "node:child_process";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const owner = opt("owner"), name = opt("name", "alice.eth");
if (!/^0x[0-9a-fA-F]{40}$/.test(owner ?? "")) { console.error("--owner 0x... is required: your throwaway address"); process.exit(2); }
const ROOT = new URL("..", import.meta.url).pathname;
const kids = [];
const run = (args) => new Promise((ok, no) => {
  const p = spawn(process.execPath, args, { cwd: ROOT, stdio: ["ignore", "pipe", "inherit"] });
  kids.push(p);
  p.stdout.on("data", (d) => { process.stdout.write(d); if (String(d).includes('"ready":true')) ok(); });
  p.on("exit", (c) => no(new Error(`${args.join(" ")} exited ${c}`)));
});
await run(["issuer/serve.mjs", "--port", "8801", "--name", name, "--owner", owner]);
await run(["key-host/serve.mjs", "8804"]);
await run(["--max-old-space-size=512", "site/serve.mjs", "--origin", "http://site-a.test:8802", "--port", "8802", "--issuer", "http://127.0.0.1:8801", "--title", "Site A", "--accent", "#2563eb"]);
await run(["--max-old-space-size=512", "site/serve.mjs", "--origin", "http://site-b.test:8803", "--port", "8803", "--issuer", "http://127.0.0.1:8801", "--title", "Site B", "--accent", "#0f766e"]);
console.log(`Ready. Enroll: http://issuer.test:8801/enroll   Sites: http://site-a.test:8802/  http://site-b.test:8803/   Ctrl-C to stop.`);
process.on("SIGINT", () => { for (const k of kids) { k.removeAllListeners("exit"); k.kill(); } process.exit(0); });
