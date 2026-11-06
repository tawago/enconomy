#!/usr/bin/env node
// W4 Gas Gift builder shape (08-wildcards.md): B's GiftP256Account pays for A's tx. No sponsor, no registry.
// Offline only: builds and signs with deterministic TEST keys, sends nothing.
//   node gift-shape.cjs selftest      golden vector vs forge (GoldenVectorGift.t.sol) + entry checks
//   node gift-shape.cjs build         print the wire JSON of a signed gift tx
const L = require("./frame-lib.cjs");
const { keccak256, toHex, pad, concat, encodeAbiParameters, encodeFunctionData, parseAbi } = L.viem;

const GIFT_DOMAIN = keccak256(toHex("enconomy.Gift.v1"));
// Frame limits: GasBenchGift.t.sol. Gift frame 20,000 on nonce key 0; 40,000 if A uses a fresh keyed lane (+20k).
const LIMITS = { f0: 4000, f1: 12000, gift: 20000, giftNewKey: 40000 };
const SIG_GAS = 2 * 6700;

// GiftP256Account.giftDigest: keccak(abi.encode(DOMAIN, chainid, gift, sender, nonceKeysHash, seq, deadline, cap, bodyHash))
function giftDigest({ chainId, gift, sender, nonceKeys, seq, deadline, cap, bodyTarget, bodyData }) {
  const keysHash = keccak256(concat([pad(toHex(BigInt(nonceKeys.length)), { size: 32 }), ...nonceKeys.map((k) => pad(toHex(BigInt(k)), { size: 32 }))]));
  const bodyHash = keccak256(concat([bodyTarget, bodyData])); // abi.encodePacked(target, data)
  const D = keccak256(encodeAbiParameters(
    [{ type: "bytes32" }, { type: "uint256" }, { type: "address" }, { type: "address" }, { type: "bytes32" }, { type: "uint256" },
     { type: "uint256" }, { type: "uint256" }, { type: "bytes32" }],
    [GIFT_DOMAIN, BigInt(chainId), gift, sender, keysHash, BigInt(seq), BigInt(deadline), BigInt(cap), bodyHash]));
  return { D, keysHash, bodyHash };
}

// Envelope: [expiry, only_verify(A), gift(B), SENDER body], entries [A over sig hash, B over D].
// B's phone needs (sender, nonceKeys, seq, deadline, cap, body): NOT the fees or gas limits, so one B signature
// covers both the estimate copy (10M body limits) and the send.
function giftTx(o = {}) {
  const A = L.testKey("deviceA"), B = L.testKey("deviceB");
  const account = o.account ?? "0x" + keccak256(toHex("chirpgas-test:P256Account(A)")).slice(26);
  const gift = o.gift ?? "0x" + keccak256(toHex("gift-test:GiftP256Account(B)")).slice(26);
  const meetBook = o.meetBook ?? "0x" + keccak256(toHex("chirpgas-test:MeetBook")).slice(26);
  const deadline = BigInt(o.deadline ?? Math.floor(Date.now() / 1000) + 900);
  const cap = BigInt(o.cap ?? 10n ** 15n);
  const nonceKeys = o.nonceKeys ?? [0n];
  const seq = BigInt(o.seq ?? 0);
  const bodyData = encodeFunctionData({ abi: parseAbi(["function met(address partner, bytes32 transcript)"]), functionName: "met",
    args: [B.address, o.transcript ?? keccak256(toHex("chirp transcript"))] });
  const { D } = giftDigest({ chainId: 1337, gift, sender: account, nonceKeys, seq, deadline, cap, bodyTarget: meetBook, bodyData });
  const giftData = encodeFunctionData({ abi: parseAbi(["function gift(uint256 cap)"]), functionName: "gift", args: [cap] });
  const fresh = nonceKeys.some((k) => BigInt(k) !== 0n) && !o.knownLane;
  const body = o.forEstimate ? { execution: 10000000, state: 10000000 } : { execution: o.bodyGas ?? 60000, state: 0 };
  const tx = {
    chainId: 1337, nonceKeys, nonceSeq: seq, sender: account,
    frames: [
      { mode: L.MODE.VERIFY, flags: 0, target: L.EXPIRY_VERIFIER, limits: { execution: LIMITS.f0, state: 0 }, value: 0, data: pad(toHex(deadline), { size: 8 }) },
      { mode: L.MODE.VERIFY, flags: 2, target: null, limits: { execution: LIMITS.f1, state: 0 }, value: 0, data: "0x" },
      { mode: L.MODE.VERIFY, flags: 1, target: gift, limits: { execution: fresh ? LIMITS.giftNewKey : LIMITS.gift, state: 0 }, value: 0, data: giftData },
      { mode: L.MODE.SENDER, flags: 0, target: meetBook, limits: body, value: 0, data: bodyData },
    ],
    signatures: [],
    fees: { maxPriorityFeePerGas: o.tip ?? 1n, maxFeePerGas: o.maxFee ?? 10n, maxFeePerBlobGas: 0 },
    blobVersionedHashes: [],
    recentRootReferences: [],
  };
  // B's entry is explicit (msg = D), so it is filled first and stays in the sig hash; A signs last.
  const sh = L.signAll(tx, [{ key: A }, { key: B, msg: D, signature: o.bSignature }]);
  // what APPROVE(payment) will debit from B (ethrex compute_tx_max_cost, no blobs): maxFee x sum of limits
  const maxCost = BigInt(tx.fees.maxFeePerGas) * tx.frames.reduce((s, f) => s + BigInt(f.limits.execution) + BigInt(f.limits.state), 0n);
  return { tx, sh, D, A, B, maxCost, cap, meta: { account, gift, meetBook, deadline, seq } };
}

// Same fixed inputs as poc-validation-rules/test/GoldenVectorGift.t.sol
function golden() {
  const bodyData = encodeFunctionData({ abi: parseAbi(["function met(address partner, bytes32 transcript)"]), functionName: "met",
    args: ["0x000000000000000000000000000000000000bb01", keccak256(toHex("acoustic transcript"))] });
  const got = giftDigest({ chainId: 1337, gift: "0x6177000000000000000000000000000000000001", sender: "0x00000000000000000000000000000000000a11ce",
    nonceKeys: [0n], seq: 0n, deadline: 1793560702n, cap: 10n ** 15n, bodyTarget: "0x000000000000000000000000000000000003b00c", bodyData });
  const want = {
    keysHash: "0xada5013122d395ba3c54772283fb069b10426056ef8ca54750cb9bb552a59e7d",
    bodyHash: "0x13813530eaeba2b9648dea89989c95fa65993283ba4775bffd689cce9af97c63",
    D: "0xc77f12778f6c3f37fee637f9c37619c303edf19138bfff0833c0cb2146cabced",
  };
  const ok = Object.keys(want).every((k) => got[k] === want[k]);
  console.log("gift golden vector vs forge (GoldenVectorGift.t.sol):", ok ? "match" : "MISMATCH " + JSON.stringify(got));
  return ok;
}

function selftest() {
  const gOk = golden();
  const { tx, sh, D, maxCost, cap } = giftTx({ deadline: 1793560702n });
  const [e0, e1] = tx.signatures.map((s) => L.checkEntry(s, tx.sender, sh));
  console.log("entry0 (A, sig hash):", e0, "| entry1 (B, D):", e1, "| D", D);
  // the point of an explicit D: the estimate copy has other body limits (other sig hash) but the same D
  const est = giftTx({ deadline: 1793560702n, forEstimate: true });
  const sameD = est.D === D && est.sh !== sh;
  console.log("estimate copy: same D, other sig hash:", sameD, "| B signs once:", est.tx.signatures[1].signature === tx.signatures[1].signature);
  const capOk = maxCost <= cap && est.maxCost <= cap;
  console.log("max cost send / estimate:", maxCost.toString(), "/", est.maxCost.toString(), "<= cap", cap.toString(), capOk);
  const sum = LIMITS.f0 + LIMITS.f1 + LIMITS.gift + SIG_GAS, sumN = LIMITS.f0 + LIMITS.f1 + LIMITS.giftNewKey + SIG_GAS;
  console.log("sidecar verify sum:", sum, "(fresh keyed lane", sumN + ") / 100000");
  // a keyed lane picks the bigger gift limit
  const keyed = giftTx({ deadline: 1793560702n, nonceKeys: [7n] });
  const limOk = keyed.tx.frames[2].limits.execution === LIMITS.giftNewKey && keyed.D !== D;
  console.log("fresh keyed lane: gift limit", keyed.tx.frames[2].limits.execution, "| D differs:", keyed.D !== D);
  if (!gOk || e0 !== "ok" || e1 !== "ok" || !sameD || !capOk || sumN > 100000 || !limOk) process.exit(1);
}

const cmd = process.argv[2];
if (cmd === "selftest") selftest();
else if (cmd === "build") console.log(JSON.stringify(L.toWire(giftTx().tx), null, 2));
else if (require.main === module) { console.error("usage: gift-shape.cjs selftest|build"); process.exit(2); }

module.exports = { giftDigest, giftTx, golden, LIMITS, SIG_GAS, GIFT_DOMAIN };
