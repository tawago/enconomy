#!/usr/bin/env python3
"""Deploy the recovery account on chain 1337. Run from examples/evp-recovery with the core up.

  python3 -I scripts/setup.py --laptop-x <hex> --funding-key-file <file> [--owner <address>]

Makes L in .env if there is none, funds it, reuses the verifiers on chain if their VK hashes match, writes .run/deploy.json.
"""
import argparse
import base64
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from backend.chain import CORE, DEPLOY, EMAIL, ENV_FILE, HERE, ORIGIN, RPC, RUN, call, cast, get_json, rpc, send  # noqa: E402

ADAPTER = "0x345631e18663fa69bbeb813549712261fb06e798"
PHONE_VK = "2991b4b80fba7cab1645dd154c75dfb0a9440f9c3f582d5df967b11b7c311aba"
PAIR_VK = "1b998943818ded4848c0cb1365265eb7e9e9b195f9c01f2e1d88dbb5a9fafbd2"
CFG_T = "(uint256,uint256,bytes32,bytes32,uint256,uint256,address)"
DELAY = 120
FUND_WEI = 50_000_000_000_000_000  # a start needs about 12.73M gas x 2 gwei up front
MIN_WEI = 30_000_000_000_000_000


def b64int(s):
    return int.from_bytes(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)), "big")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--laptop-x", required=True)
    ap.add_argument("--funding-key-file", required=True)
    ap.add_argument("--owner", default="0x" + os.urandom(20).hex())
    ap.add_argument("--artifact", default=str(HERE / "contracts/out/EvpRecoveryAccount.sol/EvpRecoveryAccount.json"))
    ap.add_argument("--adapter", default=ADAPTER, help="shape checks only: a stand-in presence verifier")
    a = ap.parse_args()

    # The verifiers must hold the VKs the core proves with. On a mismatch: fv/v1.1/circuit/forge/chain1337.py redeploys them.
    phone, pair = call(ADAPTER, "phoneVerifier()(address)"), call(ADAPTER, "pairVerifier()(address)")
    for addr, vk in ((phone, PHONE_VK), (pair, PAIR_VK)):
        if vk not in rpc("eth_getCode", addr, "latest")["result"]:
            sys.exit(f"verifier {addr} does not hold VK {vk}: redeploy with fv/v1.1/circuit/forge/chain1337.py")
    if int(call(ADAPTER, "maxAge()(uint64)")) < 1200:
        sys.exit("adapter maxAge under 1200")

    if not ENV_FILE.exists():
        ENV_FILE.touch(mode=0o600)
        ENV_FILE.write_text(f"EVP_L_KEY=0x{os.urandom(32).hex()}\n")
    key = ENV_FILE.read_text().split("=", 1)[1].strip()
    laptop = cast("wallet", "address", "--private-key", key, key=key)
    if int(cast("balance", laptop, "--rpc-url", RPC)) < MIN_WEI:
        fkey = pathlib.Path(a.funding_key_file).read_text().strip()
        send(fkey, 250000, laptop, "--value", str(FUND_WEI))  # a new account costs state gas here, 21000 reverts

    issuer = get_json(f"{CORE}/v1/config")["issuer"]  # the key that signs credentials and POPCC1
    jwk = json.loads((RUN / "keys/issuer.jwk.json").read_text())
    cfg = [str(b64int(jwk["x"])), str(b64int(jwk["y"])), cast("keccak", EMAIL), cast("keccak", ORIGIN),
           str(int(issuer["pub_x"], 16)), str(int(issuer["pub_y"], 16)), a.adapter]
    config_hash = cast("keccak", cast("abi-encode", f"c({CFG_T})", "(" + ",".join(cfg) + ")"))
    x = int(a.laptop_x, 16)
    args = cast("abi-encode", "c(address,address[],uint256,address,uint256,bytes32)", a.owner, "[]", str(DELAY), laptop, str(x), config_hash)[2:]
    art = json.loads(pathlib.Path(a.artifact).read_text())
    code = "0x" + art["bytecode"]["object"].removeprefix("0x") + args
    est = rpc("eth_estimateGas", {"from": laptop, "data": code}, "latest")
    if "result" not in est:
        sys.exit(f"estimate failed: {est}")
    r = send(key, int(est["result"], 16) * 11 // 10, "--create", code)
    d = {"account": r["contractAddress"], "laptop": laptop, "owner": a.owner, "laptopDeviceX": hex(x), "cfg": cfg,
         "configHash": config_hash, "adapter": a.adapter, "phone": phone, "pair": pair, "delay": DELAY, "tx": r["transactionHash"]}
    DEPLOY.write_text(json.dumps(d, indent=1))
    print(json.dumps({k: d[k] for k in ("account", "laptop", "owner", "laptopDeviceX", "tx")}, indent=1))


if __name__ == "__main__":
    main()
