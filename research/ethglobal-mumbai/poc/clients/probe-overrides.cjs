// Live, read-only probe on chain 1337. Two questions:
//  1. Does a P-256 entry built by frame-lib pass the signature rule? (sender with no code)
//  2. Do eth_estimateFrameTransactionGas (sidecar) / ethrex_simulateFrameTransaction (node)
//     honour an eth_call-style state override?
// Method: same tx, sender has no code. Baseline must fail at VERIFY (default code approves
// SECP256K1 only). Then inject approve-all runtime + balance at the sender via every override
// spelling we can think of. If any result differs from baseline, the override was honoured.
const L = require("./frame-lib.cjs");
const { keccak256, toHex } = L.viem;
const NODE = process.env.NODE_RPC || "https://altmempool.forshtat.com";
const SIDE = process.env.SIDECAR_RPC || "https://altmempool.forshtat.com/rpc";

// PUSH1 3, PUSH1 0, DUP1, APPROVE(offset 0, len 0, scope 3)
const APPROVE_ALL = "0x6003600080aa";
const BIG = "0x3635c9adc5dea00000"; // 1000 ETH
// The sidecar's estimate rewrites every body-frame limit to 10,000,000 (execution and state)
// BEFORE it checks signatures, so a real signature only survives if we sign with exactly that.
const BODY = 10000000;

function tx({ sender, signer, key, corrupt = false }) {
  const t = {
    chainId: 1337, nonceKeys: [0], nonceSeq: 0, sender,
    frames: [
      { mode: L.MODE.VERIFY, flags: 3, target: null, limits: { execution: 30000, state: 0 }, value: 0, data: "0x" },
      { mode: L.MODE.SENDER, flags: 0, target: "0x000000000000000000000000000000000000dEaD", limits: { execution: BODY, state: BODY }, value: 0, data: "0x" },
    ],
    signatures: [{ scheme: L.SCHEME.P256, signer, msg: "0x", signature: "0x" }],
    fees: { maxPriorityFeePerGas: 1, maxFeePerGas: 9, maxFeePerBlobGas: 0 },
    blobVersionedHashes: [], recentRootReferences: [],
  };
  t.signatures[0].signature = L.p256SignDigest(key, L.sigHash(t));
  if (corrupt) { const s = t.signatures[0].signature; t.signatures[0].signature = s.slice(0, 10) + (s[10] === "0" ? "1" : "0") + s.slice(11); }
  return t;
}
const short = (r) => JSON.stringify(r.error ?? r.result ?? r).slice(0, 420);

async function main() {
  const A = L.testKey("deviceA");
  const noCode = "0x" + keccak256(toHex("chirpgas-test:no-code-sender")).slice(26);
  const code = await L.rpc(NODE, "eth_getCode", [noCode, "latest"]);
  console.log("sender", noCode, "code", code.result, "| P256 signer", A.address);

  const cases = {
    "explicit signer=A, sender has no code": tx({ sender: noCode, signer: A.address, key: A }),
    "sender = A's own address, signer 0x": tx({ sender: A.address, signer: "0x", key: A }),
    "NEGATIVE: one signature nibble flipped": tx({ sender: noCode, signer: A.address, key: A, corrupt: true }),
  };
  const out = {};
  for (const [name, t] of Object.entries(cases)) {
    const est = await L.rpc(SIDE, "eth_estimateFrameTransactionGas", [L.toWire(t)]);
    const sim = await L.rpc(NODE, "ethrex_simulateFrameTransaction", [L.rawTx(t), "latest", { trace: false }]);
    out[name] = { est, sim };
    console.log("\n== " + name + "\n  sidecar estimate:", short(est), "\n  ethrex simulate :", short(sim));
  }

  // --- override probe on case 1 ---
  const t = cases["explicit signer=A, sender has no code"];
  const ov = { [noCode]: { code: APPROVE_ALL, balance: BIG } };
  const w = L.toWire(t);
  const probes = [
    ["sidecar estimate [tx, overrides]", SIDE, "eth_estimateFrameTransactionGas", [w, ov]],
    ["sidecar estimate [tx, 'latest', overrides]", SIDE, "eth_estimateFrameTransactionGas", [w, "latest", ov]],
    ["sidecar estimate [{...tx, stateOverride}]", SIDE, "eth_estimateFrameTransactionGas", [{ ...w, stateOverride: ov }]],
    ["ethrex simulate [raw, latest, {trace, stateOverrides}]", NODE, "ethrex_simulateFrameTransaction", [L.rawTx(t), "latest", { trace: false, stateOverrides: ov }]],
    ["ethrex simulate [raw, latest, {trace, stateOverride}]", NODE, "ethrex_simulateFrameTransaction", [L.rawTx(t), "latest", { trace: false, stateOverride: ov }]],
    ["ethrex simulate [raw, latest, {trace}, overrides] (4 params)", NODE, "ethrex_simulateFrameTransaction", [L.rawTx(t), "latest", { trace: false }, ov]],
    ["ethrex simulate [raw, overrides] (overrides as block)", NODE, "ethrex_simulateFrameTransaction", [L.rawTx(t), ov]],
  ];
  const base = { est: short(out["explicit signer=A, sender has no code"].est), sim: short(out["explicit signer=A, sender has no code"].sim) };
  console.log("\n== override probes (baseline = case 1)");
  for (const [name, url, m, p] of probes) {
    const r = await L.rpc(url, m, p);
    const s = short(r);
    const same = s === (url === SIDE ? base.est : base.sim);
    console.log("  " + name + "\n    sameAsBaseline=" + same + "  " + s);
  }
}
module.exports = { main };
if (require.main === module) main().catch((e) => { console.error("ERR", e.message); process.exit(1); });
