// FAKE WALLET. An EIP-1193 provider with a throwaway key. A script answers: no person approves anything.
// The harness injects it into every page it opens, so a stray wallet call anywhere gets logged.
import { privateKeyToAccount } from "viem/accounts";
import { hexToBytes } from "viem";
globalThis.__installTestWallet = (key) => {
  const acct = privateKeyToAccount(key);
  const log = (e) => { try { globalThis.__walletLog?.(JSON.stringify({ origin: location.origin, ...e })); } catch {} };
  globalThis.ethereum = {
    isFakeTestWallet: true,
    async request({ method, params }) {
      log({ method });
      if (method === "eth_requestAccounts" || method === "eth_accounts") return [acct.address];
      if (method === "personal_sign") {
        if (params[1].toLowerCase() !== acct.address.toLowerCase()) throw new Error("wrong account");
        return acct.signMessage({ message: { raw: hexToBytes(params[0]) } });
      }
      throw new Error(`fake wallet: ${method} not supported`);
    },
  };
};
