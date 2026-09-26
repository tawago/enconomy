#!/usr/bin/env node
// FFI prover for PresencePool e2e. Usage: node prove.mjs <mode> <abi-hex>
// mode: transfer | withdraw | ragequit. Prints ABI-encoded (pA,pB,pC,pubSignals[n]) hex on stdout.
import { LeanIMT } from "@zk-kit/lean-imt";
import { poseidon2 } from "poseidon-lite";
import * as snarkjs from "snarkjs";
import { decodeAbiParameters, encodeAbiParameters } from "viem";
import { fileURLToPath } from "url";
import path from "path";

const here = path.dirname(fileURLToPath(import.meta.url));
const K = "/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/ppe2e/keys";
const ART = "/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/pool/privacy-pools-core/packages";
const WITHDRAW_WASM = path.join(ART, "circuits/build/withdraw/withdraw_js/withdraw.wasm");
const WITHDRAW_ZKEY = path.join(ART, "circuits/trusted-setup/final-keys/withdraw.zkey"); // 0xbow production, unchanged
const COMMIT_WASM = path.join(ART, "contracts/node_modules/@0xbow/privacy-pools-core-sdk/dist/node/artifacts/commitment.wasm");
const COMMIT_ZKEY = path.join(ART, "circuits/trusted-setup/final-keys/commitment.zkey");
const T_WASM = path.join(K, "presenceTransfer.wasm");
const T_ZKEY = path.join(K, "transfer.zkey");

const h = (a, b) => poseidon2([a, b]);
const pad = (s, n) => { const a = s.map(String); while (a.length < n) a.push("0"); return a; };
function tree(leaves) { const t = new LeanIMT(h); for (const l of leaves) t.insert(l); return t; }
function mproof(t, leaf) {
  const i = t.indexOf(leaf);
  if (i < 0) throw new Error("leaf not in tree");
  return t.generateProof(i);
}

const [mode, hex, ov] = process.argv.slice(2);
const U = { type: "uint256" }, UA = { type: "uint256[]" };
let input, wasm, zkey, n;
if (mode === "transfer") {
  const [value, label, nul, sec, newNul, newSec, tv, payeePre, context, stateLeaves, presLeaves, presLeaf] =
    decodeAbiParameters([U, U, U, U, U, U, U, U, U, UA, UA, U], hex);
  const commit = (await import("poseidon-lite")).poseidon3([value, label, h(nul, sec)]);
  const st = tree(stateLeaves), sp = mproof(st, commit);
  const pt = tree(presLeaves);
  // prover uses the leaf it believes was posted; if it isn't in the tree we still feed a bogus path so the witness fails (UNSAT)
  let pp; try { pp = mproof(pt, presLeaf); } catch { pp = { siblings: [], index: 0 }; }
  input = { stateRoot: st.root, stateTreeDepth: st.depth, presenceRoot: pt.root, presenceTreeDepth: pt.depth, context,
    label, existingValue: value, existingNullifier: nul, existingSecret: sec, newNullifier: newNul, newSecret: newSec,
    transferValue: tv, payeePrecommitment: payeePre, stateSiblings: pad(sp.siblings, 32), stateIndex: sp.index,
    presenceSiblings: pad(pp.siblings, 20), presenceIndex: pp.index };
  wasm = T_WASM; zkey = T_ZKEY; n = 8;
} else if (mode === "withdraw") {
  const [value, label, nul, sec, newNul, newSec, wv, context, stateLeaves, aspLeaves] =
    decodeAbiParameters([U, U, U, U, U, U, U, U, UA, UA], hex);
  const commit = (await import("poseidon-lite")).poseidon3([value, label, h(nul, sec)]);
  const st = tree(stateLeaves), sp = mproof(st, commit);
  const at = tree(aspLeaves), ap = mproof(at, label);
  input = { withdrawnValue: wv, stateRoot: st.root, stateTreeDepth: st.depth, ASPRoot: at.root, ASPTreeDepth: at.depth, context,
    label, existingValue: value, existingNullifier: nul, existingSecret: sec, newNullifier: newNul, newSecret: newSec,
    stateSiblings: pad(sp.siblings, 32), stateIndex: sp.index, ASPSiblings: pad(ap.siblings, 32), ASPIndex: ap.index };
  wasm = WITHDRAW_WASM; zkey = WITHDRAW_ZKEY; n = 8;
} else if (mode === "ragequit") {
  const [value, label, nul, sec] = decodeAbiParameters([U, U, U, U], hex);
  input = { value, label, nullifier: nul, secret: sec };
  wasm = COMMIT_WASM; zkey = COMMIT_ZKEY; n = 4;
} else { process.exit(2); }

if (ov) Object.assign(input, JSON.parse(ov));
const strIn = JSON.parse(JSON.stringify(input, (_, v) => (typeof v === "bigint" ? v.toString() : v)));
const log = console.log; console.log = () => {};
const { proof, publicSignals } = await snarkjs.groth16.fullProve(strIn, wasm, zkey);
console.log = log;
const enc = encodeAbiParameters(
  [{ type: "uint256[2]" }, { type: "uint256[2][2]" }, { type: "uint256[2]" }, { type: `uint256[${n}]` }],
  [[BigInt(proof.pi_a[0]), BigInt(proof.pi_a[1])],
   [[BigInt(proof.pi_b[0][1]), BigInt(proof.pi_b[0][0])], [BigInt(proof.pi_b[1][1]), BigInt(proof.pi_b[1][0])]],
   [BigInt(proof.pi_c[0]), BigInt(proof.pi_c[1])], publicSignals.map(BigInt)]);
process.stdout.write(enc);
process.exit(0);
