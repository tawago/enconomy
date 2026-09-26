// One-shot SAFE relayer (Ethereum Sepolia). Reads a PoP attestation, assembles execTransaction, sends it.
//   node relay.mjs <sid> [--wait]        GET $POP_SERVER_URL/v1/session/<sid>/attestation (--wait: poll until done)
//   node relay.mjs --fixture <file.json> same, body read from a file (tests; sid taken from the body). A file with
//                                        format "pop-zk-bundle-1" (GET /zk/bundle) takes the Noir path.
// Presence path: PRESENCE=attest|noir|auto (default auto: the Safe guard's verifier has phoneVerifier() -> noir).
//   attest: GET /attestation, presence = the server's POP2 tail (PopAttestationVerifier).
//   noir:   GET /zk/bundle (public, 404 until the pair proof verifies), presence = abi.encode(NoirPresenceVerifier.Bundle).
// env: RELAYER_PK or RELAYER_KEY_FILE (gas key, default ~/.enconomy/ens-sepolia.key; never in server/), RPC (default publicnode Sepolia), POP_SERVER_URL (http://127.0.0.1:8000),
//      CHAIN_ID (11155111), OUT_DIR (./out), EXPECT_SAFE (optional: refuse any other Safe), PRINT_SIGS=1 (debug)
// Idempotent: out/<sid>.json holds the tx hash once sent; a rerun only reads the receipt, never resends.
// out/<sid>.result.json = the last stdout line (the server serves it at GET /v1/session/<sid>/relay for the phones).
// stdout: one JSON line {sid, status: success|reverted|skipped|error, error?, text?, tx_hash?, ...}
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { createPublicClient, createWalletClient, http, parseAbi, BaseError, ContractFunctionRevertedError, formatEther,
  encodeAbiParameters } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";

export const ABI = parseAbi([
  "function nonce() view returns (uint256)",
  "function getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256) view returns (bytes32)",
  "function execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes) payable returns (bool)",
  "function deviceOwner(address,bytes32) view returns (address)",
  // PopSafeGuard
  "error NotInit()", "error NoPresence()", "error BadPresence()", "error UnknownDevice()", "error SameOwner()",
  "error DelegateCallNotAllowed()", "error RefundNotAllowed()", "error ForbiddenSelfCall()", "error NotRecoveryTx()",
  "error TooEarly()", "error PresentOwnersMustSign()", "error AnnouncementExpired()", "error GuardNotReady()",
  "error BadConfig()", "error BadNonce()", "error NotOwner()", "error BadDevice()",
  // PopAttestationVerifier
  "error BadAttestation()", "error Expired()",
  // NoirPresenceVerifier
  "function verifier() view returns (address)", "function phoneVerifier() view returns (address)",
  "error BadPublicInputs(uint256)", "error Stale()", "error ProofRejected(uint256)", "error BadCodeAttest(uint256)",
]);
const EXEC_SUCCESS = "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e";
const GUARD_SLOT = "0x4a204f620c8c5ccdca3fd54d003badd85ba500436a431f0cbda4f558c93c34c8";
const Z = "0x0000000000000000000000000000000000000000";

// spec 02 §8.4 (names adapted to PopSafeGuard + PopAttestationVerifier)
export const TEXT = {
  NoPresence: "No presence proof attached",
  BadAttestation: "Presence proof signature invalid (wrong attester key?)",
  BadPresence: "Presence proof invalid",
  Expired: "Presence proof expired (15 min). Meet again.",
  UnknownDevice: "This phone isn't registered to this wallet",
  unknown_device: "This phone isn't registered to this wallet",
  SameOwner: "Both phones belong to the same owner",
  PresentOwnersMustSign: "Both owners' phones must sign",
  stale_nonce: "Another transaction went first. Start again.",
  context_mismatch: "Transaction changed. Start again.",
  not_near: "Owners weren't together. Nothing was sent.",
  "att_refused:unattested_device": "POP_UNATTESTED_ALLOW doesn't list this iPhone's device_id. Set it, restart the server, new session",
  "att_refused:nonprod_humans": "Both people need an Orb-verified World ID (production).",
  "att_refused:human_missing": "Waiting for the other person's World ID",
  "att_refused:bad_chain": "Server is on another chain (POP_CHAIN_ID)",
  owner_sigs_missing: "An owner didn't sign at Confirm",
  wrong_safe: "Not the Safe this relayer serves",
  no_guard: "This Safe has no PoP guard",
  GS024: "Owner signature invalid or for an old nonce",
  GS020: "Not enough / badly ordered owner signatures",
  GS026: "Not enough / badly ordered owner signatures",
  GS013: "Transfer failed (balance?)",
  Stale: "ZK presence proof too old. Meet again.",
  ProofRejected: "ZK presence proof rejected onchain",
  BadPublicInputs: "ZK proof doesn't match this transaction",
  BadCodeAttest: "Code attestation signature invalid (Safe issuer != server issuer key?)",
  zk_not_ready: "ZK pair proof not ready yet",
};

// NoirPresenceVerifier.Bundle
const BUNDLE = [{ type: "tuple", components: [
  { name: "notBefore", type: "uint64" }, { name: "sid", type: "bytes16" },
  { name: "proofA", type: "bytes" }, { name: "pubA", type: "bytes32[]" },
  { name: "proofB", type: "bytes" }, { name: "pubB", type: "bytes32[]" },
  { name: "proofPair", type: "bytes" }, { name: "pubPair", type: "bytes32[]" },
  { name: "ccSigA", type: "bytes" }, { name: "ccSigB", type: "bytes" },
] }];
const hx = (s) => (s.startsWith("0x") ? s : "0x" + s).toLowerCase();

/** GET /zk/bundle body -> abi.encode(Bundle) hex (NoirPresenceVerifier.verifyPresence `presence`). */
export function noirPresence(b) {
  const p = b.proofs, cc = b.code_attest || {};
  if (!p?.A?.proof || !p?.B?.proof || !p?.pair?.proof || !cc.A?.sig_hex || !cc.B?.sig_hex) throw new Error("bundle incomplete");
  return encodeAbiParameters(BUNDLE, [{
    notBefore: BigInt(b.not_before), sid: hx(b.sid),
    proofA: hx(p.A.proof), pubA: p.A.public_inputs.map(hx),
    proofB: hx(p.B.proof), pubB: p.B.public_inputs.map(hx),
    proofPair: hx(p.pair.proof), pubPair: p.pair.public_inputs.map(hx),
    ccSigA: hx(cc.A.sig_hex), ccSigB: hx(cc.B.sig_hex),
  }]);
}

/** Safe >= 1.3 contract signatures for P256Owner owners, sorted by address (spec 02 §4.4, §8.3). */
export function buildSignatures(items) {
  const s = [...items].sort((a, b) => (BigInt(a.owner) < BigInt(b.owner) ? -1 : 1));
  let stat = "", dyn = "";
  const off0 = 65 * s.length;
  for (const it of s) {
    const off = off0 + dyn.length / 2;
    stat += it.owner.slice(2).toLowerCase().padStart(64, "0") + off.toString(16).padStart(64, "0") + "00";
    dyn += (64).toString(16).padStart(64, "0") + it.sig.slice(2).toLowerCase();
  }
  return "0x" + stat + dyn;
}

/** PopSafeGuard framing: presence | u32 BE len(presence) | "POPV" (0x504f5056). */
export function framePresence(presenceHex) {
  const p = presenceHex.replace(/^0x/, "").toLowerCase();
  return p + (p.length / 2).toString(16).padStart(8, "0") + "504f5056";
}

function errName(e) {
  if (e instanceof BaseError) {
    const r = e.walk((x) => x instanceof ContractFunctionRevertedError);
    if (r?.data?.errorName) return r.data.errorName === "Error" ? String(r.data.args?.[0]) : r.data.errorName;
    if (r?.reason) return r.reason;
    if (r?.signature) return "revert:" + r.signature;
  }
  return "revert:" + (e.shortMessage || e.message).slice(0, 120);
}

async function main(args) {
  const OUT = process.env.OUT_DIR || "./out";
  fs.mkdirSync(OUT, { recursive: true });
  const done = (code, obj) => {
    if (obj.error && !obj.text) obj.text = TEXT[obj.error] ?? TEXT[String(obj.error).split(":")[0]];
    if (obj.path === undefined && path) obj.path = path;
    if (obj.sid && /^[0-9a-f]+$/i.test(obj.sid)) {
      try { fs.writeFileSync(`${OUT}/${obj.sid}.result.json`, JSON.stringify({ ...obj, at: Math.floor(Date.now() / 1000) }) + "\n"); } catch {}
    }
    console.log(JSON.stringify(obj));
    process.exit(code);
  };
  let path = null;
  const CHAIN_ID = Number(process.env.CHAIN_ID || 11155111);
  const chain = { ...sepolia, id: CHAIN_ID };
  const transport = http(process.env.RPC || "https://ethereum-sepolia-rpc.publicnode.com");
  const pub = createPublicClient({ chain, transport });
  const explorer = CHAIN_ID === 11155111 ? "https://sepolia.etherscan.io/tx/" : null;

  const SERVER = process.env.POP_SERVER_URL || "http://127.0.0.1:8000";
  const wait = args.includes("--wait");
  let att, bundle = null;
  if (args[0] === "--fixture") {
    att = JSON.parse(fs.readFileSync(args[1], "utf8"));
    if (att.format === "pop-zk-bundle-1") {
      bundle = att;
      att = { session_id: bundle.session_id, state: "done", verdict: bundle.verdict, context: bundle.context,
        safe: bundle.safe };
    }
  }
  else if (args[0]) {
    const url = `${SERVER}/v1/session/${args[0]}/attestation`;
    const until = Date.now() + (wait ? 180_000 : 0);
    for (;;) {
      const r = await fetch(url);
      if (!r.ok) done(2, { sid: args[0], status: "error", error: `attestation_http_${r.status}` });
      att = await r.json();
      if (att.state === "done" || att.state === "aborted" || Date.now() > until) break;
      await new Promise((ok) => setTimeout(ok, 500));
    }
  } else done(2, { status: "error", error: "usage: node relay.mjs <sid> [--wait] | --fixture <file>" });
  const sid = att.session_id;
  const outFile = `${OUT}/${sid}.json`;

  // 0. already sent? report the receipt, never resend (restart safety)
  if (fs.existsSync(outFile)) {
    const prev = JSON.parse(fs.readFileSync(outFile, "utf8"));
    const rc = await pub.waitForTransactionReceipt({ hash: prev.tx_hash, pollingInterval: 500, timeout: 60_000 });
    done(rc.status === "success" ? 0 : 1, { sid, status: rc.status === "success" ? "success" : "reverted",
      tx_hash: prev.tx_hash, block: Number(rc.blockNumber), resent: false, link: explorer ? explorer + prev.tx_hash : null });
  }
  const skip = (error, extra = {}) => {
    fs.writeFileSync(`${OUT}/${sid}.skip`, error + "\n");
    done(1, { sid, status: "skipped", error, ...extra });
  };

  // 1. shape checks (both paths)
  const c = att.context || {};
  if (att.state !== "done") done(3, { sid, status: "pending", error: "not_done", state: att.state });
  if (att.verdict !== "NEAR") skip("not_near");
  if (c.kind !== "safe-tx" || c.chain_id !== CHAIN_ID) skip("bad_attestation_body");
  if (process.env.EXPECT_SAFE && c.consumer.toLowerCase() !== process.env.EXPECT_SAFE.toLowerCase()) skip("wrong_safe");
  const safe = c.consumer, t = c.safe_tx;

  // 1b. which presence: the guard's verifier decides (PRESENCE overrides)
  const slot = await pub.getStorageAt({ address: safe, slot: GUARD_SLOT });
  const guard = "0x" + (slot || "0x").slice(-40);
  if (!slot || BigInt(slot) === 0n) skip("no_guard");
  path = bundle ? "noir" : (process.env.PRESENCE || "auto");
  if (path === "auto") {
    try {
      const v = await pub.readContract({ address: guard, abi: ABI, functionName: "verifier" });
      await pub.readContract({ address: v, abi: ABI, functionName: "phoneVerifier" });
      path = "noir";
    } catch { path = "attest"; }
  }
  let devs, sigs;
  if (path === "noir") {
    if (!bundle) {
      const url = `${SERVER}/v1/session/${sid}/zk/bundle`;
      const until = Date.now() + (wait ? 300_000 : 0);
      for (;;) {
        const r = await fetch(url);
        if (r.ok) { bundle = await r.json(); break; }
        if (r.status !== 404) done(2, { sid, status: "error", error: `bundle_http_${r.status}` });
        if (Date.now() > until) done(3, { sid, status: "pending", error: "zk_not_ready" });
        await new Promise((ok) => setTimeout(ok, 1000));
      }
    }
    if (bundle.context?.ctx_hash !== c.ctx_hash) skip("context_mismatch");
    devs = { A: bundle.devices?.A?.device_hash, B: bundle.devices?.B?.device_hash };
    sigs = bundle.safe?.owner_sigs || {};
  } else {
    if (att.att_refused) skip("att_refused:" + att.att_refused);
    if (!att.att || att.att.v !== "pop-safe-v2") skip("bad_attestation_body");
    if (att.att.expiry <= Math.floor(Date.now() / 1000) + 30) skip("Expired");
    devs = { A: att.att.dev_a, B: att.att.dev_b };
    sigs = att.safe?.owner_sigs || {};
  }
  if (!sigs.A || !sigs.B) skip("owner_sigs_missing");

  // 2. hash + nonce against the live Safe
  const h = await pub.readContract({ address: safe, abi: ABI, functionName: "getTransactionHash",
    args: [t.to, BigInt(t.value), t.data, t.operation, BigInt(t.safe_tx_gas), BigInt(t.base_gas), BigInt(t.gas_price),
      t.gas_token, t.refund_receiver, BigInt(t.nonce)] });
  if (h.toLowerCase() !== c.ctx_hash.toLowerCase()) skip("context_mismatch");
  const n = await pub.readContract({ address: safe, abi: ABI, functionName: "nonce" });
  if (n !== BigInt(t.nonce)) skip("stale_nonce");

  // 3. the owners of the two session devices
  const items = [];
  for (const role of ["A", "B"]) {
    if (!devs[role]) skip("unknown_device", { role });
    const owner = await pub.readContract({ address: guard, abi: ABI, functionName: "deviceOwner", args: [safe, devs[role]] });
    if (owner === Z) skip("unknown_device", { role });
    items.push({ owner, sig: sigs[role] });
  }
  let presence;
  try { presence = path === "noir" ? noirPresence(bundle) : att.att.tail_hex; } catch (e) { skip("bad_bundle", { detail: e.message }); }
  const signatures = buildSignatures(items) + framePresence(presence);
  if (process.env.PRINT_SIGS) console.error("signatures", signatures);

  // 4. simulate, estimate x1.2, send (pending nonce, one sender), write out/<sid>.json BEFORE waiting
  // gas key: RELAYER_PK, else the key file (default: the shared deployer key, ~/.enconomy/ens-sepolia.key)
  const keyFile = process.env.RELAYER_KEY_FILE || `${process.env.HOME}/.enconomy/ens-sepolia.key`;
  const relayerPk = process.env.RELAYER_PK || (fs.existsSync(keyFile) ? fs.readFileSync(keyFile, "utf8").trim() : "");
  if (!relayerPk) done(2, { sid, status: "error", error: "RELAYER_PK / RELAYER_KEY_FILE not set" });
  const account = privateKeyToAccount(relayerPk);
  const bal = await pub.getBalance({ address: account.address });
  if (bal < 10n ** 15n) console.error(`warn: relayer ${account.address} has ${formatEther(bal)} ETH`);
  const wallet = createWalletClient({ account, chain, transport });
  const callArgs = [t.to, BigInt(t.value), t.data, t.operation, BigInt(t.safe_tx_gas), BigInt(t.base_gas),
    BigInt(t.gas_price), t.gas_token, t.refund_receiver, signatures];
  const call = { account, address: safe, abi: ABI, functionName: "execTransaction", args: callArgs };
  try { await pub.simulateContract(call); } catch (e) { skip(errName(e)); }
  let gas;
  try { gas = (await pub.estimateContractGas(call)) * 12n / 10n; } catch (e) { skip(errName(e)); }
  const nonce = await pub.getTransactionCount({ address: account.address, blockTag: "pending" });
  const hash = await wallet.writeContract({ ...call, gas, nonce });
  fs.writeFileSync(outFile, JSON.stringify({ tx_hash: hash, safe_tx_hash: h }) + "\n");
  console.error(`sent ${hash}`);
  const rc = await pub.waitForTransactionReceipt({ hash, pollingInterval: 500, timeout: 60_000 });
  const ok = rc.status === "success" && rc.logs.some((l) => l.address.toLowerCase() === safe.toLowerCase()
    && l.topics[0] === EXEC_SUCCESS && l.topics[1]?.toLowerCase() === h.toLowerCase());
  done(ok ? 0 : 1, { sid, status: ok ? "success" : "reverted", tx_hash: hash, safe_tx_hash: h,
    block: Number(rc.blockNumber), gas_used: Number(rc.gasUsed), link: explorer ? explorer + hash : null });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((e) => {
    console.log(JSON.stringify({ status: "error", error: (e.shortMessage || e.message || String(e)).slice(0, 300) }));
    process.exit(2);
  });
}
