#!/usr/bin/env python3
"""Deploy the real contracts to chain 1337 and run verifyPresence: eth_call, wrong deviceB, estimate, plain tx.
python3 -I chain1337.py <forge out dir> <file with a funded 1337 key>. Prints a JSON summary. Plain txs only."""
import json, os, pathlib, subprocess, sys, urllib.request

RPC = "https://altmempool.forshtat.com"
GAS_PRICE = "2000000"
HERE = pathlib.Path(__file__).parent
FX = HERE / "fixtures/field_180ca04b"
OUT = pathlib.Path(sys.argv[1])
KEY = pathlib.Path(sys.argv[2]).read_text().strip()

NONCE = 0xefa53688db41bdc0ef206e14cf42c5de874443d5b6d44c6e5fc1b0345738db85
DEVICE_A = 0xa3add80f0b308b87f91990aad20b1ba09eac2329cc4ca80940a29c5b27becd0c
DEVICE_B = 0xf567fcdaa2cb002d7b91763b5314008716328fb8d943c0a6f592badceae25b59
QX = 0x9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6
QY = 0x4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3
NOT_BEFORE, DEADLINE, MAX_AGE = 1789999400, 1790000600, 1200
EXPECT = "52ba618629bf0b0f2cfae5bf76fb9daad9e3195ac7c4036cf7b064b5e7f2f0a6"  # keccak from the forge test


def rpc(method, *params):
    req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "curl/8"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def cast(*a):
    p = subprocess.run(["cast", *a], capture_output=True, text=True)
    if p.returncode:
        sys.exit("cast failed: " + p.stderr.replace(KEY, "<key>")[:2000])  # the command line holds the key, never print it
    return p.stdout.strip()


def send(gas, *a):
    r = json.loads(cast("send", "--legacy", "--gas-price", GAS_PRICE, "--gas-limit", str(gas), "--json", "--rpc-url", RPC, "--private-key", KEY, *a))
    assert r["status"] == "0x1", r
    return r


DEPLOYS = []


def create(name, code):
    # Code deposit on this chain costs far more than on Osaka (EIP-8037 state gas), so ask the node.
    est = rpc("eth_estimateGas", {"from": ME, "data": code}, "latest")
    r = send(int(est["result"], 16) * 11 // 10, "--create", code)
    DEPLOYS.append({"name": name, "address": r["contractAddress"], "tx": r["transactionHash"], "gas": int(r["gasUsed"], 16)})
    return r["contractAddress"]


def art(f, c):
    return json.loads((OUT / f / f"{c}.json").read_text())


def link(a, libs):
    code = a["bytecode"]["object"].removeprefix("0x")
    for _, names in a["bytecode"]["linkReferences"].items():
        for name, refs in names.items():
            for r in refs:
                s = r["start"] * 2
                code = code[:s] + libs[name].removeprefix("0x").lower() + code[s + 40:]
    int(code, 16)
    return "0x" + code


def verifier(file, name):
    libs = {n: create(f"{name}.{n}", link(art(file, n), {})) for n in ("RelationsLib", "ZKTranscriptLib")}
    return create(name, link(art(file, name), libs))


def blob(b):
    return len(b).to_bytes(32, "big") + b + b"\0" * (-len(b) % 32)


def bundle():
    parts = [(FX / p).read_bytes() for p in ("A/proof", "A/public_inputs", "B/proof", "B/public_inputs",
                                             "pair/proof", "pair/public_inputs", "A/ccsig", "B/ccsig")]
    tails, off, heads = [], 8 * 32, []
    for i, b in enumerate(parts):
        t = (len(b) // 32).to_bytes(32, "big") + b if i in (1, 3, 5) else blob(b)
        heads.append(off.to_bytes(32, "big"))
        tails.append(t)
        off += len(t)
    return (32).to_bytes(32, "big") + b"".join(heads) + b"".join(tails)


def calldata(device_b):
    sel = bytes.fromhex(cast("sig", "verifyPresence(bytes32,uint256,uint256,uint256,uint256,uint64,uint256,bytes)")[2:])
    head = [NONCE, DEVICE_A, device_b, QX, QY, NOT_BEFORE, DEADLINE, 8 * 32]
    return sel + b"".join(x.to_bytes(32, "big") for x in head) + blob(bundle())


ME = cast("wallet", "address", "--private-key", KEY)
good = calldata(DEVICE_B)
assert cast("keccak", "0x" + good.hex())[2:] == EXPECT, "calldata differs from the forge test"
res = {"chainId": int(rpc("eth_chainId")["result"], 16), "calldata": len(good),
       "calldata_zero": good.count(0), "calldata_nonzero": len(good) - good.count(0)}
assert res["chainId"] == 1337
res["balance_before"] = rpc("eth_getBalance", ME, "latest")["result"]
res["deploys"] = DEPLOYS

phone = verifier("PhoneVerifier.sol", "PhoneVerifier")
pair = verifier("PairNamedVerifier.sol", "PairNamedVerifier")
args = cast("abi-encode", "c(address,address,uint64)", phone, pair, str(MAX_AGE))[2:]
adapter = create("EvpNoirPresenceVerifier", link(art("EvpNoirPresenceVerifier.sol", "EvpNoirPresenceVerifier"), {}) + args)
wrapper = create("PresenceLog", link(art("PresenceLog.sol", "PresenceLog"), {}))
res.update(phone=phone, pair=pair, adapter=adapter, wrapper=wrapper)

G = hex(16_000_000)
SEL = "0x7dd7b02c"
wrapped = bytes.fromhex(cast("sig", "run(address,bytes)")[2:]) + bytes.fromhex(adapter[2:].rjust(64, "0")) + \
    (64).to_bytes(32, "big") + blob(good)


def intrinsic(b):
    return 21000 + 4 * b.count(0) + 16 * (len(b) - b.count(0))


def accepts(to, data, gas):
    r = rpc("eth_call", {"from": ME, "to": to, "data": "0x" + data.hex(), "gas": hex(gas)}, "latest")
    return r.get("result", "").startswith(SEL)


def smallest(to, data, lo, hi):
    """Smallest eth_call gas that accepts, by search."""
    assert not accepts(to, data, lo) and accepts(to, data, hi)
    while hi - lo > 1:
        m = (lo + hi) // 2
        if accepts(to, data, m):
            hi = m
        else:
            lo = m
    return hi


def calls(tx):
    t = rpc("debug_traceTransaction", tx, {"tracer": "callTracer"})["result"]["calls"][0]
    out = {"adapter": [int(t["gas"], 16), int(t["gasUsed"], 16)]}
    out["verifiers"] = [[c["to"], int(c["gas"], 16), int(c["gasUsed"], 16)] for c in t["calls"]
                        if c["to"] not in ("0x0000000000000000000000000000000000000002", "0x0000000000000000000000000000000000000100")]
    return out


res["eth_call"] = rpc("eth_call", {"to": adapter, "data": "0x" + good.hex(), "gas": G}, "latest").get("result")
res["eth_call_wrong_deviceB"] = rpc("eth_call", {"to": adapter, "data": "0x" + calldata(DEVICE_B ^ 1).hex(), "gas": G}, "latest")["error"]["data"]
res["estimate_adapter"] = int(rpc("eth_estimateGas", {"from": ME, "to": adapter, "data": "0x" + good.hex()}, "latest")["result"], 16)
res["estimate_wrapper"] = int(rpc("eth_estimateGas", {"from": ME, "to": wrapper, "data": "0x" + wrapped.hex()}, "latest")["result"], 16)
res["wrapped_bytes"] = len(wrapped)
res["intrinsic_adapter"], res["intrinsic_wrapped"] = intrinsic(good), intrinsic(wrapped)
i = res["intrinsic_adapter"]
res["min_after_intrinsic_adapter"] = smallest(adapter, good, i + 11_400_000, i + 11_700_000) - i
i = res["intrinsic_wrapped"]
res["min_after_intrinsic_wrapper"] = smallest(wrapper, wrapped, i + 11_500_000, i + 12_000_000) - i

# The plain tx, with exactly 12,000,000 left after intrinsic gas.
limit = i + 12_000_000
r = send(limit, wrapper, "0x" + wrapped.hex())
ev = r["logs"][0]
res["tx"] = {"hash": r["transactionHash"], "block": int(r["blockNumber"], 16), "status": r["status"], "limit": limit,
             "gasUsed": int(r["gasUsed"], 16), "event_ret": ev["data"][2:10], "event_gasUsed": int(ev["data"][66:130], 16),
             "trace": calls(r["transactionHash"])}
res["balance_after"] = rpc("eth_getBalance", ME, "latest")["result"]
print(json.dumps(res, indent=1))
