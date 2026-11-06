// The 4-frame EVP start through our own sidecar. Job JSON on stdin, EVP_L_KEY in env, result JSON on stdout.
// fv/v1.1/circuit/frame_tx/send_frame.cjs with the phone signature gone. Entry 0 is an empty ARBITRARY: ethrex's default
// code reads index 1 for a payment-only frame, so L can't sit at 0. job.simulate: ethrex_simulateFrameTransaction, free.
const fs = require("fs");
const L = require("../../../research/ethglobal-mumbai/poc/clients/frame-lib.cjs");

const NODE = process.env.EVP_RPC ?? "https://altmempool.forshtat.com";
const { encodeFunctionData, parseAbi, pad, toHex, keccak256 } = L.viem;
const s = JSON.parse(fs.readFileSync(0, "utf8"));
const priv = process.env.EVP_L_KEY;
const address = "0x" + keccak256(toHex(L.secp256k1.getPublicKey(priv.slice(2), false).slice(1))).slice(26);
if (address.toLowerCase() !== s.laptop.toLowerCase()) throw new Error("wrong laptop key");
const laptop = { priv, address };

const abi = parseAbi([
  "struct Config { uint256 issuerX; uint256 issuerY; bytes32 emailHash; bytes32 audHash; uint256 popIssuerX; uint256 popIssuerY; address presenceVerifier; }",
  "function evpVerify(uint64 notBefore, bytes16 sid, uint256 qx, uint256 qy, Config cfg, bytes bundle)",
  "function startRotationEvp(address newKey, bytes32 sessionTag, uint256 deadline, Config cfg, bytes token, uint256 offs)",
]);
const c = s.cfg;
const cfg = { issuerX: BigInt(c[0]), issuerY: BigInt(c[1]), emailHash: c[2], audHash: c[3], popIssuerX: BigInt(c[4]), popIssuerY: BigInt(c[5]), presenceVerifier: c[6] };
const frame1 = encodeFunctionData({ abi, functionName: "evpVerify", args: [BigInt(s.notBefore), s.sid, BigInt(s.qx), BigInt(s.qy), cfg, s.bundle] });
const frame3 = encodeFunctionData({ abi, functionName: "startRotationEvp", args: [s.newKey, s.sessionTag, BigInt(s.deadline), cfg, s.token, BigInt(s.offs)] });

async function main() {
  const nonce = BigInt((await L.rpc(NODE, "eth_getTransactionCount", [s.account, "latest"])).result);
  const tx = {
    chainId: 1337, nonceKeys: [0], nonceSeq: nonce, sender: s.account,
    frames: [
      { mode: L.MODE.VERIFY, flags: 0, target: L.EXPIRY_VERIFIER, limits: { execution: 4_000, state: 0 }, value: 0, data: pad(toHex(BigInt(s.deadline)), { size: 8 }) },
      { mode: L.MODE.VERIFY, flags: 2, target: s.account, limits: { execution: 12_000_000, state: 0 }, value: 0, data: frame1 },
      { mode: L.MODE.VERIFY, flags: 1, target: s.laptop, limits: { execution: 8_000, state: 0 }, value: 0, data: "0x" },
      { mode: L.MODE.SENDER, flags: 0, target: s.account, limits: { execution: 110_000, state: 100_000 }, value: 0, data: frame3 },
    ],
    signatures: [
      { scheme: L.SCHEME.ARBITRARY, signer: "0x", msg: "0x", signature: "0x" },
      { scheme: L.SCHEME.SECP256K1, signer: s.laptop, msg: "0x", signature: "0x" },
    ],
    fees: { maxPriorityFeePerGas: 1_000_000_000n, maxFeePerGas: 2_000_000_000n, maxFeePerBlobGas: 0 },
    blobVersionedHashes: [], recentRootReferences: [],
  };
  tx.signatures[1].signature = L.secpSignDigest(laptop, L.sigHash(tx));

  const out = { localTxHash: L.txHash(tx) };
  if (s.simulate) {
    const sim = await L.rpc(NODE, "ethrex_simulateFrameTransaction", [L.rawTx(tx), "latest", { trace: false }]);
    console.log(JSON.stringify({ ...out, simulated: sim.result ?? sim.error }));
    return;
  }
  const sent = await L.rpc(s.sidecar, "eth_sendFrameTransaction", [L.toWire(tx)]);
  if (sent.error || !sent.result) {
    console.log(JSON.stringify({ ...out, rejected: sent.error ?? sent }));
    return;
  }
  out.hash = sent.result;
  let receipt = null;
  for (let i = 0; i < 40 && !receipt; i += 1) {
    receipt = (await L.rpc(NODE, "eth_getTransactionReceipt", [out.hash])).result;
    if (!receipt) await new Promise((d) => setTimeout(d, 5_000));
  }
  if (!receipt) {
    console.log(JSON.stringify({ ...out, notMined: true }));
    return;
  }
  out.block = Number(receipt.blockNumber);
  out.status = receipt.status;
  out.gasUsed = Number(receipt.gasUsed);
  out.frames = (receipt.frameReceipts ?? []).map((f) => ({ status: f.status, gasUsed: Number(f.gasUsed), logs: f.logs?.length ?? 0 }));
  console.log(JSON.stringify(out));
}
main().catch((e) => { console.error("error:", e.message); process.exit(1); });
