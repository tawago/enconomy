// Does the alt mempool enforce a verify gas cap, and does stake raise it?
//
//   node verify-cap.cjs
//   SIDECAR_RPC=https://other-devnet/rpc node verify-cap.cjs
//
// Read-only. eth_estimateFrameTransactionGas never sends a transaction.

const L = require("./frame-lib.cjs");

const SIDECAR = process.env.SIDECAR_RPC
  || "https://altmempool.forshtat.com/rpc";

const GAS_LEVELS = [
  90_000, 100_000, 100_001, 150_000, 250_000, 1_000_000, 1_500_000,
];
const UNSTAKED = "0x1111111111111111111111111111111111111111";
const ANY_TARGET = "0x000000000000000000000000000000000000dEaD";

const call = (method, params = []) => L.rpc(SIDECAR, method, params);
const short = (addr) => `${addr.slice(0, 6)}…${addr.slice(-4)}`;

function frameTx(sender, verifyGas) {
  const frame = (mode, flags, target, gas) => ({
    mode,
    flags,
    target,
    limits: { execution: gas, state: 0 },
    value: 0,
    data: "0x",
  });

  return {
    chainId: 1337,
    nonceKeys: [0],
    nonceSeq: 0,
    sender,
    frames: [
      frame(L.MODE.VERIFY, 3, null, verifyGas),
      frame(L.MODE.SENDER, 0, ANY_TARGET, 50_000),
    ],
    signatures: [],
    fees: {
      maxPriorityFeePerGas: 1_000_000_000n,
      maxFeePerGas: 2_000_000_000n,
      maxFeePerBlobGas: 0,
    },
    blobVersionedHashes: [],
    recentRootReferences: [],
  };
}

async function hitsCap(sender, gas) {
  const tx = L.toWire(frameTx(sender, gas));
  const res = await call("eth_estimateFrameTransactionGas", [tx]);
  return String(res.error?.message ?? "").includes("exceeds MAX_VERIFY_GAS");
}

async function findStakedSender() {
  const { result } = await call("skandha_explorer_listReputation");
  return result.items.find((entry) => entry.isStaked)?.address;
}

async function countRealRejections() {
  const { result } = await call("skandha_explorer_listAdmissions", [
    { limit: 1000 },
  ]);
  const over = result.items.filter((row) =>
    JSON.stringify(row).includes("exceeds MAX_VERIFY_GAS"));
  return { over: over.length, total: result.items.length };
}

async function main() {
  const version = (await call("web3_clientVersion")).result;
  const staked = await findStakedSender();

  console.log(`sidecar  ${SIDECAR}`);
  console.log(`version  ${version}`);
  console.log(`unstaked ${short(UNSTAKED)}`);
  console.log(`staked   ${staked ? short(staked) : "none found"}`);
  console.log();
  console.log("verify gas   unstaked   staked");
  console.log("----------   --------   --------");

  for (const gas of GAS_LEVELS) {
    const unstaked = await hitsCap(UNSTAKED, gas);
    const withStake = staked ? await hitsCap(staked, gas) : null;
    const label = (over) => (over === null ? "-" : over ? "REJECTED" : "ok");

    console.log(
      gas.toLocaleString("en-US").padStart(10),
      " ",
      label(unstaked).padEnd(8),
      " ",
      label(withStake),
    );
  }

  const { over, total } = await countRealRejections();
  console.log();
  console.log("ok = under the cap. The fake tx may still fail later.");
  console.log(`log: ${over} of last ${total} entries hit this cap`);
}

main().catch((err) => {
  console.error(`error: ${err.message}`);
  process.exit(1);
});
