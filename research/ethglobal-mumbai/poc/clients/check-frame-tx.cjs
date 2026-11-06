// Read-only check: re-encode a mined frame tx from the alt-mempool devnet (chain 1337)
// with our own encoder, compare the tx hash, recompute sig_hash, recover the secp256k1 signer.
// No keys, no sends. Uses the viem already installed in ../../../../relayer.
// Usage: node check-frame-tx.cjs <rpcUrl> <txHash>
const { createRequire } = require("module");
const req = createRequire(require("path").join(__dirname, "../../../../relayer/package.json"));
const { toRlp, keccak256, toHex, hexToBigInt, recoverAddress, concat } = req("viem");

const [rpc, hash] = process.argv.slice(2);
const n = (h) => (h && hexToBigInt(h) !== 0n ? toHex(hexToBigInt(h)) : "0x"); // RLP int
async function call(method, params) {
  const r = await fetch(rpc, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  const j = await r.json(); if (j.error) throw new Error(JSON.stringify(j.error)); return j.result;
}
// tracer layout: [chain_id, nonce_keys, nonce_seq, sender, frames, signatures, fees, blob_hashes, recent_root_refs]
function envelope(tx, elide) {
  return [
    n(tx.chainId),
    tx.nonceKeys.map(n),
    n(tx.nonceSeq),
    tx.sender,
    tx.frames.map((f) => [n(f.mode), n(f.flags), f.to ?? "0x", [n(f.gasLimit), n(f.stateLimit)], n(f.value), f.data]),
    tx.signatures.map((s) => [n(s.scheme), s.signer ?? "0x", s.msg ?? "0x", elide && (s.msg ?? "0x") === "0x" ? "0x" : s.signature]),
    [n(tx.maxPriorityFeePerGas), n(tx.maxFeePerGas), n(tx.maxFeePerBlobGas)],
    tx.blobVersionedHashes ?? [],
    (tx.recentRootReferences ?? []).map((r) => [n(r.sourceId), n(r.slot), r.root]),
  ];
}
(async () => {
  const tx = await call("eth_getTransactionByHash", [hash]);
  if (!tx) throw new Error("tx not found");
  const raw = concat(["0x06", toRlp(envelope(tx, false))]);
  const sigHash = keccak256(concat(["0x06", toRlp(envelope(tx, true))]));
  console.log("type", tx.type, "chainId", Number(tx.chainId), "frames", tx.frames.length, "sigs", tx.signatures.length);
  console.log("rawLen", (raw.length - 2) / 2, "hashMatch", keccak256(raw) === tx.hash);
  console.log("sigHash", sigHash);
  for (const s of tx.signatures) {
    if (Number(s.scheme) !== 1) { console.log("scheme", s.scheme, "(not secp256k1, skipped)"); continue; }
    const v = parseInt(s.signature.slice(2, 4), 16), r = "0x" + s.signature.slice(4, 68), ss = "0x" + s.signature.slice(68, 132);
    const who = await recoverAddress({ hash: s.msg && s.msg !== "0x" ? s.msg : sigHash, signature: { r, s: ss, yParity: v } });
    const resolved = s.signer && s.signer !== "0x" ? s.signer : tx.sender; console.log("recovered", who, "resolvedSigner", resolved, "match", who.toLowerCase() === resolved.toLowerCase(), "nonceKeys", tx.nonceKeys.length, "rootRefs", (tx.recentRootReferences ?? []).length);
  }
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });
