// Pluggable ENS lookup. Interface: { kind, resolve(normalizedName) -> address string or null }. Nothing here caches: each login reads again.
import { readFileSync } from "node:fs";
import { createPublicClient, defineChain, http } from "viem";
import { mainnet } from "viem/chains";

// `table` is an object, or the path of a JSON file that's read again on each lookup, so the demo can repoint a name while running.
export const tableLookup = (table) => ({
  kind: "local-table",
  resolve: async (name) => (typeof table === "string" ? JSON.parse(readFileSync(table, "utf8")) : table)[name] ?? null,
});

// Read-only. getEnsAddress goes through the Universal Resolver contract. Address record. Site servers use it with --ens mainnet. The issuer's server uses the table.
export function mainnetLookup(rpcUrl, { onRequest } = {}) {
  const client = createPublicClient({ chain: mainnet, transport: http(rpcUrl, { onFetchRequest: onRequest, timeout: 20000 }) });
  return { kind: "mainnet-universal-resolver", client, resolve: (name) => client.getEnsAddress({ name }) };
}

// Same read, on any chain that has a Universal Resolver. Site servers use it with --ens deployment.
export function chainLookup({ rpcUrl, chainId, universalResolver }) {
  const chain = defineChain({
    id: chainId, name: `chain-${chainId}`, nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
    rpcUrls: { default: { http: [rpcUrl] } },
    contracts: { ensUniversalResolver: { address: universalResolver } },
  });
  const client = createPublicClient({ chain, transport: http(rpcUrl, { timeout: 20000 }) });
  return { kind: `chain-${chainId}-universal-resolver`, client, resolve: (name) => client.getEnsAddress({ name }) };
}
