// Send a frame tx whose VERIFY burns more than 100k gas on chain 1337.
//
//   node heavy-verify.cjs setup             make a key, fund it, deploy wallet
//   node heavy-verify.cjs send <gas> [url]  send through a sidecar
//   node heavy-verify.cjs send-data <gas> <bytes> [url]  same, with <bytes> of VERIFY frame data
//   node heavy-verify.cjs probe-setup       deploy the precompile probe wallet
//   node heavy-verify.cjs probe <name> [url]  call a precompile in VERIFY
//
// url defaults to a local sidecar. Sends real devnet transactions, with a
// throwaway key in devnet/.run/ (git-ignored). The wallet is test-only.

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { createRequire } = require("module");
const L = require("./frame-lib.cjs");

const relayer = createRequire(
  require("path").join(__dirname, "../../../../relayer/package.json"),
);
const { generatePrivateKey } = relayer("viem/accounts");

const NODE = "https://altmempool.forshtat.com";
const LOCAL_SIDECAR = "http://localhost:14337/rpc/";
const RECIPIENT = "0x8943545177806ED17B9F23F0a21ee5948eCaa776";

const DEVNET = path.resolve(__dirname, "../../devnet");
const RUN = path.join(DEVNET, ".run");
const KEY_FILE = path.join(RUN, "heavy.key");
const STATE_FILE = path.join(RUN, "heavy.json");
const GENESIS_SRC = path.join(
  DEVNET, ".vendor/sidecar/test/e2e/helpers.ts",
);

// Each loop iteration of the wallet costs 40 gas.
const GAS_PER_LOOP = 40;
// Room for everything in VERIFY outside the loop.
const VERIFY_OVERHEAD = 5_000;

// Runtime: loop CALLDATALOAD(0) times, require the signer the protocol
// verified to be the owner, then APPROVE(0, 0, execution and payment).
function walletInitCode(owner) {
  const runtime = [
    "5f35", //                 n = calldataload(0)
    "5b", //                   2: loop
    "8015600f57", //           if n == 0 goto 15
    "600190036002" + "56", //  n -= 1, goto 2
    "5b50", //                 15: drop n
    "5f5fb4", //               sigparam(0, RESOLVED_SIGNER)
    "73" + owner.slice(2).toLowerCase(),
    "14603057", //             if equal goto 48
    "5f5ffd", //               revert
    "5b", //                   48
    "60035f5faa", //           approve(0, 0, 3)
  ].join("");

  const size = (runtime.length / 2).toString(16).padStart(2, "0");
  return `0x60${size}8060095f395ff3${runtime}`;
}

// Runtime: calldata is [32-byte target][input]. STATICCALL target with input,
// require success and non-empty output (a failed P-256 check returns nothing),
// then the same signer check and APPROVE as the wallet above.
function probeInitCode(owner) {
  const runtime = [
    "60203603", //     len = calldatasize - 32
    "8060205f37", //   calldatacopy(0, 32, len)
    "60205f825f5f355afa", // staticcall(gas, target, 0, len, 0, 32)
    "3d151516", //     ok = success && returndatasize != 0
    "601c57", //       if ok goto 28
    "5f5ffd", //       revert
    "5b50", //         28: drop len
    "5f5fb4", //       sigparam(0, RESOLVED_SIGNER)
    "73" + owner.slice(2).toLowerCase(),
    "14603d57", //     if equal goto 61
    "5f5ffd", //       revert
    "5b", //           61
    "60035f5faa", //   approve(0, 0, 3)
  ].join("");

  const size = (runtime.length / 2).toString(16).padStart(2, "0");
  return `0x60${size}8060095f395ff3${runtime}`;
}

const word = (n) => n.toString(16).padStart(64, "0");
const p256Vector = fs.readFileSync(
  path.join(__dirname, "p256verify-vector.hex"), "utf8",
).trim();

// Valid inputs, so each one returns output.
const PRECOMPILES = {
  sha256: { address: 0x02n, input: "abcd" },
  modexp: {
    address: 0x05n,
    input: word(1n) + word(1n) + word(1n) + "020305",
  },
  pairing: { address: 0x08n, input: "" }, // empty input is defined: true
  p256: { address: 0x100n, input: p256Vector },
};

function cast(...args) {
  return execFileSync("cast", args, { encoding: "utf8" }).trim();
}

function genesisKey() {
  const src = fs.readFileSync(GENESIS_SRC, "utf8");
  const found = src.match(/MINING_SENDER_PRIVATE_KEY\s*=\s*\n?\s*"(0x\w{64})"/);
  if (!found) throw new Error("published genesis key not found");
  return found[1];
}

function setup() {
  fs.mkdirSync(RUN, { recursive: true });
  if (!fs.existsSync(KEY_FILE)) {
    fs.writeFileSync(KEY_FILE, `${generatePrivateKey()}\n`, { mode: 0o600 });
  }
  const key = L.secpKeyFromFile(KEY_FILE);
  const legacy = ["--legacy", "--gas-price", "2000000", "--rpc-url", NODE];

  console.log(`owner  ${key.address}`);
  if (cast("balance", key.address, "--rpc-url", NODE) === "0") {
    cast(
      "send", key.address, "--value", "0.5ether", "--gas-limit", "250000",
      "--private-key", genesisKey(), ...legacy,
    );
  }
  console.log(`funded ${cast("balance", key.address, "--rpc-url", NODE)} wei`);

  const receipt = JSON.parse(cast(
    "send", "--value", "0.1ether", "--gas-limit", "6000000",
    "--private-key", key.priv, "--json", ...legacy,
    "--create", walletInitCode(key.address),
  ));
  if (receipt.status !== "0x1") throw new Error("wallet deploy reverted");

  const wallet = receipt.contractAddress;
  fs.writeFileSync(STATE_FILE, JSON.stringify({ wallet }, null, 2));
  console.log(`wallet ${wallet}`);
}

function setupProbe() {
  const key = L.secpKeyFromFile(KEY_FILE);
  const receipt = JSON.parse(cast(
    "send", "--value", "0.05ether", "--gas-limit", "6000000",
    "--private-key", key.priv, "--json",
    "--legacy", "--gas-price", "2000000", "--rpc-url", NODE,
    "--create", probeInitCode(key.address),
  ));
  if (receipt.status !== "0x1") throw new Error("probe deploy reverted");

  const state = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  state.probe = receipt.contractAddress;
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  console.log(`probe  ${state.probe}`);
}

function burnData(verifyGas) {
  const loops = BigInt(
    Math.floor((verifyGas - VERIFY_OVERHEAD) / GAS_PER_LOOP),
  );
  return L.viem.pad(L.viem.toHex(loops), { size: 32 });
}

function buildTx({ wallet, owner, nonce, verifyGas, verifyData }) {
  const tx = {
    chainId: 1337,
    nonceKeys: [0],
    nonceSeq: nonce,
    sender: wallet,
    frames: [{
      mode: L.MODE.VERIFY,
      flags: 3,
      target: null,
      limits: { execution: verifyGas, state: 0 },
      value: 0,
      data: verifyData,
    }, {
      mode: L.MODE.SENDER,
      flags: 0,
      target: RECIPIENT,
      limits: { execution: 50_000, state: 200_000 },
      value: 1_000_000_000,
      data: "0x",
    }],
    signatures: [{
      scheme: L.SCHEME.SECP256K1,
      signer: owner,
      msg: "0x",
      signature: `0x${"00".repeat(65)}`,
    }],
    fees: {
      maxPriorityFeePerGas: 1_000_000_000n,
      maxFeePerGas: 2_000_000_000n,
      maxFeePerBlobGas: 0,
    },
    blobVersionedHashes: [],
    recentRootReferences: [],
  };
  return tx;
}

async function waitForReceipt(hash) {
  for (let tries = 0; tries < 30; tries += 1) {
    const { result } = await L.rpc(
      NODE, "eth_getTransactionReceipt", [hash],
    );
    if (result) return result;
    await new Promise((done) => setTimeout(done, 4_000));
  }
  return null;
}

async function submit({ wallet, verifyGas, verifyData, sidecar }) {
  const key = L.secpKeyFromFile(KEY_FILE);
  const nonceHex = (await L.rpc(
    NODE, "eth_getTransactionCount", [wallet, "latest"],
  )).result;

  const tx = buildTx({
    wallet,
    owner: key.address,
    nonce: BigInt(nonceHex),
    verifyGas,
    verifyData,
  });
  tx.signatures[0].signature = L.secpSignDigest(key, L.sigHash(tx));

  console.log(`sidecar    ${sidecar}`);
  console.log(`wallet     ${wallet}`);
  console.log(`verify gas ${verifyGas.toLocaleString("en-US")}`);

  const sent = await L.rpc(
    sidecar, "eth_sendFrameTransaction", [L.toWire(tx)],
  );
  if (sent.error) {
    console.log(`REJECTED   ${sent.error.message}`);
    process.exitCode = 2;
    return;
  }

  const hash = sent.result;
  console.log(`ADMITTED   ${hash}`);

  const receipt = await waitForReceipt(hash);
  if (!receipt) {
    console.log("NOT MINED  after 2 minutes");
    process.exitCode = 3;
    return;
  }

  const frames = (receipt.frameReceipts ?? [])
    .map((frame) => `${frame.status}/${Number(frame.gasUsed)}`)
    .join(" ");
  console.log(`MINED      block ${Number(receipt.blockNumber)}`);
  console.log(`status     ${receipt.status}`);
  console.log(`frames     ${frames}`);
  console.log(`gas used   ${Number(receipt.gasUsed)}`);
}

function loadState() {
  return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
}

function send(verifyGas, sidecar) {
  return submit({
    wallet: loadState().wallet,
    verifyGas,
    verifyData: burnData(verifyGas),
    sidecar,
  });
}

// The burn word first, then random bytes up to size. The wallet only reads the
// first word. Random, so the bytes cost what a real proof would: mostly non-zero.
function sendWithData(verifyGas, size, sidecar) {
  const fill = crypto.randomBytes(size - 32).toString("hex");
  console.log(`frame data ${size} bytes`);
  return submit({
    wallet: loadState().wallet,
    verifyGas,
    verifyData: `${burnData(verifyGas)}${fill}`,
    sidecar,
  });
}

function probe(name, sidecar) {
  const target = PRECOMPILES[name];
  if (!target) throw new Error(`unknown precompile ${name}`);
  console.log(`precompile ${name}`);
  return submit({
    wallet: loadState().probe,
    verifyGas: 150_000,
    verifyData: `0x${word(target.address)}${target.input}`,
    sidecar,
  });
}

function fail(err) {
  console.error(`error: ${err.message}`);
  process.exit(1);
}

const [command, arg, url, dataUrl] = process.argv.slice(2);
const sidecar = url ?? LOCAL_SIDECAR;
if (command === "setup") {
  setup();
} else if (command === "probe-setup") {
  setupProbe();
} else if (command === "send" && arg) {
  send(Number(arg), sidecar).catch(fail);
} else if (command === "send-data" && arg && url) {
  sendWithData(Number(arg), Number(url), dataUrl ?? LOCAL_SIDECAR).catch(fail);
} else if (command === "probe" && arg) {
  probe(arg, sidecar).catch(fail);
} else {
  console.error("usage: heavy-verify.cjs setup | send <gas> [url]");
  console.error("       heavy-verify.cjs send-data <gas> <bytes> [url]");
  console.error("       heavy-verify.cjs probe-setup | probe <name> [url]");
  process.exit(1);
}
