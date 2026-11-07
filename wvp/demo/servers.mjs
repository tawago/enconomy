// Starts the issuer, key host and two sites, then waits. Doesn't start Chrome. Use it to try a real wallet with a throwaway account.
// Usage: node demo/servers.mjs --owner 0xYOUR_THROWAWAY_ADDRESS [--name alice.eth] [--no-issuer] [--ens deployment --deployment file.json] [--org blob.eth]
// The two sites hold verifying keys in memory, about 1.1 GiB each. --no-issuer starts no issuer and no key host, and the sites load no
// keys: named login only. Both sites are name-only. ENS is a local table file that demo/repoint.mjs can change, unless --ens says otherwise.
import { writeFileSync, rmSync } from "node:fs";
import { TABLE_FILE } from "./lib/table.mjs";
import { spawn } from "node:child_process";
const opt = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const owner = opt("owner"), name = opt("name", "alice.eth");
if (!/^0x[0-9a-fA-F]{40}$/.test(owner ?? "")) { console.error("--owner 0x... is required: your throwaway address"); process.exit(2); }
const ROOT = new URL("..", import.meta.url).pathname;
const kids = [];
const noIssuer = process.argv.includes("--no-issuer");
writeFileSync(TABLE_FILE, JSON.stringify({ [name]: owner }, null, 2));
const ens = opt("ens", "table");
const site = ["--name-only", ...(noIssuer ? ["--no-proofs"] : []), "--ens", ens, ...(ens === "table" ? ["--table", TABLE_FILE] : []), ...(ens === "mainnet" && opt("rpc") ? ["--rpc", opt("rpc")] : []), ...(ens === "deployment" ? ["--deployment", opt("deployment")] : []), ...(opt("org") ? ["--org", opt("org")] : [])];
const run = (args) => new Promise((ok, no) => {
  const p = spawn(process.execPath, args, { cwd: ROOT, stdio: ["ignore", "pipe", "inherit"] });
  kids.push(p);
  p.stdout.on("data", (d) => { process.stdout.write(d); if (String(d).includes('"ready":true')) ok(); });
  p.on("exit", (c) => no(new Error(`${args.join(" ")} exited ${c}`)));
});
if (!noIssuer) {
  await run(["issuer/serve.mjs", "--port", "8801", "--name", name, "--owner", owner, "--table", TABLE_FILE]);
  await run(["key-host/serve.mjs", "8804"]);
}
await run(["issuer/serve-approve.mjs", "--port", "8806", "--name", name, ...(noIssuer ? [] : ["--anonymous"])]);
await run(["--max-old-space-size=512", "site/serve.mjs", "--origin", "http://blobzon.test:8802", "--port", "8802", "--issuer", "http://127.0.0.1:8801", "--brand", "blobzon", ...site]);
await run(["--max-old-space-size=512", "site/serve.mjs", "--origin", "http://blobchannel.test:8803", "--port", "8803", "--issuer", "http://127.0.0.1:8801", "--brand", "blobchannel", ...site]);
console.log(`Ready. Approval page: http://enroll.test:8806/enroll   Sites: http://blobzon.test:8802/  http://blobchannel.test:8803/   Ctrl-C to stop.`);
process.on("SIGINT", () => { for (const k of kids) { k.removeAllListeners("exit"); k.kill(); } rmSync(TABLE_FILE, { force: true }); process.exit(0); });
