// Pluggable ENS lookup. Interface: { resolve(normalizedName) -> address string or null }.
import { createPublicClient, http } from "viem";
import { mainnet } from "viem/chains";

export const tableLookup = (table) => ({
  kind: "local-table",
  resolve: async (name) => table[name] ?? null,
});

// Read-only. getEnsAddress goes through the Universal Resolver contract. Address record. Not wired into the login flow.
export function mainnetLookup(rpcUrl, { onRequest } = {}) {
  const client = createPublicClient({ chain: mainnet, transport: http(rpcUrl, { onFetchRequest: onRequest, timeout: 20000 }) });
  return { kind: "mainnet-universal-resolver", client, resolve: (name) => client.getEnsAddress({ name }) };
}
