// Prints {label: address or null} for <label>.<org>, read through the universal resolver as the sites do.
// A label that couldn't be read is left out. The backend passes this with node -e, run from the ENS folder, which holds viem and deployment.json.
import fs from "node:fs";
import { createPublicClient, defineChain, http } from "viem";

const d = JSON.parse(fs.readFileSync("deployment.json"));
const chain = defineChain({
  id: d.chainId, name: `chain-${d.chainId}`, nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
  rpcUrls: { default: { http: [d.rpc] } },
  contracts: { ensUniversalResolver: { address: d.universalResolver } },
});
const pub = createPublicClient({ chain, transport: http(d.rpc, { timeout: 20_000 }) });
const out = {};
await Promise.all(process.argv.slice(1).map(async (label) => {
  try { out[label] = await pub.getEnsAddress({ name: `${label}.${d.org.name}` }); } catch (e) { console.error(label, e.shortMessage ?? e.message); }
}));
console.log(JSON.stringify(out));
