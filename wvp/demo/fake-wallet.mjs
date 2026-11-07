// FAKE WALLET. An EIP-1193 provider with keys the demo hands it at runtime, usually throwaway. A script answers: no person approves anything.
// The harness injects it into every page it opens, so a stray wallet call anywhere gets logged.
import { privateKeyToAccount } from "viem/accounts";
import { hexToBytes } from "viem";
// One key or several. It plays one at a time, the first until ethereum.__use(i) picks another.
globalThis.__installTestWallet = (keys) => {
  const accts = [keys].flat().map((k) => privateKeyToAccount(k));
  let acct = accts[0];
  const log = (e) => { try { globalThis.__walletLog?.(JSON.stringify({ origin: location.origin, ...e })); } catch {} };
  globalThis.ethereum = {
    isFakeTestWallet: true,
    __use(i) { acct = accts[i]; },
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
