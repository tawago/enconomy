// The 4-frame EVP start of DESIGN 4.1 through our own sidecar. Frame 3 carries a junk email token.
//   node send_frame.cjs <work> <sesign_raw binary> <B.seblob> [sidecar url]
// <work> holds session.json, bundle.hex and laptop.key from frame_tx.py. Prints JSON. Never prints a key.
// FRAME1_LIMIT=<gas> SIMULATE=1: ask ethrex_simulateFrameTransaction instead of sending. Costs nothing.
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const L = require("../../../../research/ethglobal-mumbai/poc/clients/frame-lib.cjs");

const NODE = "https://altmempool.forshtat.com";
const { encodeFunctionData, parseAbi, pad, toHex, concat } = L.viem;
const [work, sesignRaw, blob, url = "http://localhost:14337/rpc/"] = process.argv.slice(2);
const s = JSON.parse(fs.readFileSync(path.join(work, "session.json")));
const bundle = fs.readFileSync(path.join(work, "bundle.hex"), "utf8").trim();
const laptop = L.secpKeyFromFile(path.join(work, "laptop.key"));
if (laptop.address.toLowerCase() !== s.laptop.toLowerCase()) throw new Error("wrong laptop key");

const abi = parseAbi([
  "struct Config { uint256 issuerX; uint256 issuerY; bytes32 emailHash; bytes32 audHash; uint256 popIssuerX; uint256 popIssuerY; address presenceVerifier; }",
  "function evpVerify(uint64 notBefore, bytes16 sid, uint256 qx, uint256 qy, Config cfg, bytes bundle)",
  "function startRotationEvp(address newKey, bytes32 sessionTag, uint256 deadline, Config cfg, bytes token, uint256 offs)",
]);
const c = s.cfg;
const cfg = { issuerX: BigInt(c[0]), issuerY: BigInt(c[1]), emailHash: c[2], audHash: c[3], popIssuerX: BigInt(c[4]), popIssuerY: BigInt(c[5]), presenceVerifier: c[6] };
const frame1 = encodeFunctionData({ abi, functionName: "evpVerify", args: [BigInt(s.notBefore), s.sid, BigInt(s.qx), BigInt(s.qy), cfg, bundle] });
const junk = toHex("junk email token, not an EVT");
const frame3 = encodeFunctionData({ abi, functionName: "startRotationEvp", args: [s.newKey, s.sessionTag, BigInt(s.deadline), cfg, junk, 0n] });

async function main() {
  const nonce = BigInt((await L.rpc(NODE, "eth_getTransactionCount", [s.account, "latest"])).result);
  const tx = {
    chainId: 1337, nonceKeys: [0], nonceSeq: nonce, sender: s.account,
    frames: [
      { mode: L.MODE.VERIFY, flags: 0, target: L.EXPIRY_VERIFIER, limits: { execution: 4_000, state: 0 }, value: 0, data: pad(toHex(BigInt(s.deadline)), { size: 8 }) },
      { mode: L.MODE.VERIFY, flags: 2, target: s.account, limits: { execution: Number(process.env.FRAME1_LIMIT ?? 12_000_000), state: 0 }, value: 0, data: frame1 },
      { mode: L.MODE.VERIFY, flags: 1, target: s.laptop, limits: { execution: 8_000, state: 0 }, value: 0, data: "0x" },
      { mode: L.MODE.SENDER, flags: 0, target: s.account, limits: { execution: 110_000, state: 100_000 }, value: 0, data: frame3 },
    ],
    signatures: [],
    fees: { maxPriorityFeePerGas: 1_000_000_000n, maxFeePerGas: 2_000_000_000n, maxFeePerBlobGas: 0 },
    blobVersionedHashes: [], recentRootReferences: [],
  };

  // The phone signs ctx raw, with the enclave key of role B.
  const rs = execFileSync(sesignRaw, [blob, s.ctx.slice(2)], { encoding: "utf8" }).trim();
  const r = BigInt("0x" + rs.slice(0, 64));
  let ss = BigInt("0x" + rs.slice(64));
  if (ss > L.N256 / 2n) ss = L.N256 - ss;
  const phoneSig = concat([pad(toHex(r), { size: 32 }), pad(toHex(ss), { size: 32 }), pad(s.qx, { size: 32 }), pad(s.qy, { size: 32 })]);
  const entry = { scheme: L.SCHEME.P256, signer: s.newKey, msg: s.ctx, signature: phoneSig };
  if (L.p256Check(entry, s.account, s.ctx) !== "ok") throw new Error("phone signature over raw ctx does not verify");

  const sh = L.signAll(tx, [
    { key: { address: s.newKey }, msg: s.ctx, signature: phoneSig },
    { key: laptop, scheme: L.SCHEME.SECP256K1 },
  ]);
  const raw = L.rawTx(tx);
  const out = {
    sigHash: sh, localTxHash: L.txHash(tx), rawBytes: (raw.length - 2) / 2,
    frameDataBytes: tx.frames.map((f) => (f.data.length - 2) / 2),
    frame1Zero: Buffer.from(frame1.slice(2), "hex").filter((b) => b === 0).length,
  };
  const head = await L.rpc(NODE, "eth_getBlockByNumber", ["latest", false]);
  out.chainNow = Number(head.result.timestamp);
  out.deadlineLeft = s.deadline - out.chainNow;

  if (process.env.SIMULATE) {
    const sim = await L.rpc(NODE, "ethrex_simulateFrameTransaction", [raw, "latest", { trace: true }]);
    console.log(JSON.stringify(process.env.SIMULATE === "brief" ? (sim.result ? { ok: sim.result.status ?? sim.result.valid, frames: sim.result.frames?.map((f) => [f.status, f.gasUsed]) } : sim.error) : sim));
    return;
  }

  const sent = await L.rpc(url, "eth_sendFrameTransaction", [L.toWire(tx)]);
  if (sent.error || !sent.result) {
    out.rejected = sent.error ?? sent;
    console.log(JSON.stringify(out, null, 1));
    process.exit(2);
  }
  out.hash = sent.result;
  console.error("admitted", out.hash);
  let receipt = null;
  for (let i = 0; i < 40 && !receipt; i += 1) {
    receipt = (await L.rpc(NODE, "eth_getTransactionReceipt", [out.hash])).result;
    if (!receipt) await new Promise((d) => setTimeout(d, 5_000));
  }
  if (!receipt) {
    out.notMined = true;
    console.log(JSON.stringify(out, null, 1));
    process.exit(3);
  }
  out.block = Number(receipt.blockNumber);
  out.status = receipt.status;
  out.gasUsed = Number(receipt.gasUsed);
  out.frames = (receipt.frameReceipts ?? []).map((f) => ({ status: f.status, gasUsed: Number(f.gasUsed), logs: f.logs?.length ?? 0 }));
  out.receiptKeys = Object.keys(receipt);
  console.log(JSON.stringify(out, null, 1));
}
main().catch((e) => { console.error("error:", e.message); process.exit(1); });
