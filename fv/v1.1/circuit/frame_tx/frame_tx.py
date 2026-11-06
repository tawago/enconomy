#!/usr/bin/env python3
"""Real frame tx through evpVerify on chain 1337. Mac side. Keys stay on the Mac, proving runs elsewhere (prove.sh).

python3 -I frame_tx.py deploy  <work> <account artifact> <funding key file>   new L + fresh account. L's key goes in <work>
python3 -I frame_tx.py session <work> <old witness dir> <enclave dir> [slack] picks ctx, patches the phone witnesses, re-signs
python3 -I frame_tx.py bundle  <work> <enclave dir> <fixture dir>             POPCC1, bundle, eth_call at the adapter

<work> is outside the repo and holds L's key and session.json. Witnesses go to ./work for the prover, delete them after.
<old witness dir> has Prover_A.toml and Prover_B.toml, the phone witnesses of fixture 180ca04b_48k from gen_inputs.py.
Only nonce, valid_at, the transcript nonce, the transcript signature, exp and the credential signature change. Audio does not.
"""
import json, os, pathlib, re, subprocess, sys, tempfile, urllib.request

RPC = "https://altmempool.forshtat.com"
GAS_PRICE = "2000000"
HERE = pathlib.Path(__file__).resolve().parent
OLD = json.loads((HERE.parent / "forge/fixtures/field_180ca04b/chain1337.json").read_text())
ADAPTER, PHONE, PAIR = OLD["adapter"], OLD["phone"], OLD["pair"]
N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
CFG_T = "(uint256,uint256,bytes32,bytes32,uint256,uint256,address)"
EMAIL_HASH = "0x9e2c0cedad43a65e524ec636197b290e6d3b38ac6eb7dbf4d492b656021d2db8"  # DESIGN section 3 vector. No real token in this step.
AUD_HASH = "0x40a200302bc729ecd1978338601741801f5a8c0d8b981a0c2af99ca739b006d0"
DELAY = 120
FUND = "0.05ether"
CRED_LIFE = 30 * 86400


def rpc(method, *params):
    req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "curl/8"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def run(*a, key=None):
    p = subprocess.run(a, capture_output=True, text=True)
    if p.returncode:
        msg = p.stderr
        sys.exit(f"{a[0]} {a[1]} failed: " + (msg.replace(key, "<key>") if key else msg)[:2000])
    return p.stdout.strip()


def cast(*a, key=None):
    return run("cast", *a, key=key)


def send(key, gas, *a):
    r = json.loads(cast("send", "--legacy", "--gas-price", GAS_PRICE, "--gas-limit", str(gas), "--json", "--rpc-url", RPC,
                        "--private-key", key, *a, key=key))
    assert r["status"] == "0x1", r
    return r


def call(to, sig, *args):
    return cast("call", to, sig, *[str(x) for x in args], "--rpc-url", RPC).split()[0]


def state(work):
    return json.loads((pathlib.Path(work) / "session.json").read_text())


def save(work, s):
    (pathlib.Path(work) / "session.json").write_text(json.dumps(s, indent=1))


def pem_pub(pem):
    txt = run("openssl", "ec", "-in", pem, "-pubout", "-text", "-noout")
    h = "".join(re.search(r"pub:\s*((?:[0-9a-f:\s])+)", txt).group(1).split()).replace(":", "")
    assert h[:2] == "04" and len(h) == 130
    return int(h[2:66], 16), int(h[66:], 16)


def toml(path):
    out = {}
    for line in pathlib.Path(path).read_text().splitlines():
        k, v = line.split(" = ", 1)
        out[k] = v
    return out


def low_s(r_s):
    r, s = r_s[:32], int.from_bytes(r_s[32:], "big")
    return r + (N - s if s > N // 2 else s).to_bytes(32, "big")


def der_rs(der):
    assert der[0] == 0x30 and der[2] == 0x02
    rl = der[3]
    r = int.from_bytes(der[4:4 + rl], "big")
    assert der[4 + rl] == 0x02
    return r.to_bytes(32, "big") + int.from_bytes(der[6 + rl:6 + rl + der[5 + rl]], "big").to_bytes(32, "big")


def issuer_sign(pem, msg):
    with tempfile.TemporaryDirectory() as d:
        m, s = pathlib.Path(d, "m"), pathlib.Path(d, "s")
        m.write_bytes(msg)
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem, "-out", str(s), str(m)], check=True)
        return low_s(der_rs(s.read_bytes()))


def bytes_arr(b):
    return "[" + ", ".join(str(x) for x in b) + "]"


def arr_bytes(v):
    return bytes(int(x) for x in json.loads(v))


def deploy(work, artifact, funding_file):
    work = pathlib.Path(work)
    for sig, want in (("phoneVerifier()(address)", PHONE), ("pairVerifier()(address)", PAIR)):
        assert call(ADAPTER, sig).lower() == want.lower()
    max_age = int(call(ADAPTER, "maxAge()(uint64)"))
    assert max_age >= 1200, max_age

    lf = work / "laptop.key"
    if not lf.exists():
        lf.touch(mode=0o600)
        lf.write_text("0x" + os.urandom(32).hex() + "\n")
    lkey = lf.read_text().strip()
    laddr = cast("wallet", "address", "--private-key", lkey, key=lkey)
    fkey = pathlib.Path(funding_file).read_text().strip()
    fund = send(fkey, 250000, laddr, "--value", FUND)  # a new account costs state gas here, 21000 reverts

    a = json.loads(pathlib.Path(artifact).read_text())
    keys = {r: json.loads((HERE.parent.parent.parent.parent / "research/sound-bound/spikes/zk/enclave/keys" / f"{r}.seblob.json").read_text()) for r in "AB"}
    qx, qy = int(keys["B"]["pub_x"], 16), int(keys["B"]["pub_y"], 16)
    x_a = int(keys["A"]["pub_x"], 16)
    ix, iy = pem_pub(str(HERE.parent.parent.parent.parent / "research/sound-bound/spikes/zk/enclave/keys/issuer_dev.pem"))
    assert (ix, iy) == (0x9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6,
                        0x4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3)
    # EVP issuer X, Y: never reached in VERIFY and the junk token stops before them. Any words do, they are only hashed.
    cfg = ["1", "2", EMAIL_HASH, AUD_HASH, str(ix), str(iy), ADAPTER]
    cfg_tuple = "(" + ",".join(cfg) + ")"
    config_hash = cast("keccak", cast("abi-encode", f"c({CFG_T})", cfg_tuple))
    # Nobody signs as owner here. It only has to differ from newKey.
    owner = "0x" + os.urandom(20).hex()
    args = cast("abi-encode", "c(address,address[],uint256,address,uint256,bytes32)", owner, "[]", str(DELAY), laddr, str(x_a), config_hash)[2:]
    code = a["bytecode"]["object"].removeprefix("0x") + args
    est = rpc("eth_estimateGas", {"from": laddr, "data": "0x" + code}, "latest")
    assert "result" in est, est
    r = send(lkey, int(est["result"], 16) * 11 // 10, "--create", "0x" + code)
    acct = r["contractAddress"]
    s = dict(laptop=laddr, owner=owner, account=acct, adapter=ADAPTER, phone=PHONE, pair=PAIR, maxAge=max_age, delay=DELAY,
             cfg=cfg, configHash=config_hash, qx=hex(qx), qy=hex(qy), deviceA=hex(x_a), fund_tx=fund["transactionHash"],
             deploy={"tx": r["transactionHash"], "gas": int(r["gasUsed"], 16), "block": int(r["blockNumber"], 16),
                     "runtime_bytes": len(a["deployedBytecode"]["object"]) // 2 - 1})
    assert call(acct, "laptopDeviceX()(uint256)") == str(x_a)
    assert call(acct, "configHash()(bytes32)") == config_hash
    s["recoveryNonce_at_deploy"] = int(call(acct, "recoveryNonce()(uint256)"))
    s["account_nonce_at_deploy"] = int(rpc("eth_getTransactionCount", acct, "latest")["result"], 16)
    save(work, s)
    print(json.dumps({k: s[k] for k in ("laptop", "account", "deploy", "recoveryNonce_at_deploy", "account_nonce_at_deploy", "maxAge")}, indent=1))


def session(work, old, enclave, slack=1100):
    s = state(work)
    old, enclave = pathlib.Path(old), pathlib.Path(enclave)
    block = rpc("eth_getBlockByNumber", "latest", False)["result"]
    t_chain = int(block["timestamp"], 16)
    qx, qy = int(s["qx"], 16), int(s["qy"], 16)
    new_key = cast("to-check-sum-address", "0x" + cast("keccak", cast("abi-encode", "c(uint256,uint256)", str(qx), str(qy)))[-40:])
    rn = int(call(s["account"], "recoveryNonce()(uint256)"))
    tag, sid = "0x" + os.urandom(32).hex(), "0x" + os.urandom(16).hex()
    not_before, valid_at, deadline = t_chain - 60, t_chain, t_chain + int(slack)
    assert not_before <= valid_at <= deadline + 300 and deadline <= valid_at + s["maxAge"]
    ctx = call(s["account"], "evpCtx(address,bytes32,uint256)(bytes32)", new_key, tag, deadline)
    pop = call(s["account"], "popNonceFor(bytes32,uint64,bytes16)(bytes32)", ctx, not_before, sid)
    nonce = bytes.fromhex(pop[2:])
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    exp = (valid_at + CRED_LIFE).to_bytes(8, "big")
    out = HERE / "work"
    out.mkdir(exist_ok=True)
    pem = str(enclave / "keys/issuer_dev.pem")
    for role in "AB":
        src = old / f"Prover_{role}.toml"
        w = toml(src)
        assert w["role_b"] == ("true" if role == "B" else "false") and w["valid_at"] == "1790000000"
        t = bytearray(arr_bytes(w["t"]))
        assert len(t) == 311 and t[5] == 0x41 + (role == "B")
        k = json.loads((enclave / f"keys/{role}.seblob.json").read_text())
        assert t[40:104].hex() == k["pub_x"] + k["pub_y"], "witness is not this enclave key"
        t[7:39] = nonce
        j = json.loads(run(str(enclave / "sesign"), "sign", str(enclave / f"keys/{role}.seblob"), bytes(t).hex()))
        sig = low_s(bytes.fromhex(j["r"]) + bytes.fromhex(j["s"]))
        cred = b"SBcred3" + bytes(t[40:104]) + exp + arr_bytes(w["hold"])
        assert len(cred) == 111
        w.update(nonce_hi=f'"{nh}"', nonce_lo=f'"{nl}"', valid_at=str(valid_at), t=bytes_arr(t), sig=bytes_arr(sig),
                 exp=bytes_arr(exp), csig=bytes_arr(issuer_sign(pem, cred)))
        (out / f"{role}.toml").write_text("".join(f"{a} = {b}\n" for a, b in w.items()))
    p = toml(HERE.parent / "forge/fixtures/field_180ca04b/pair/Prover.toml")
    p.update(nonce_hi=f'"{nh}"', nonce_lo=f'"{nl}"')
    (out / "pair.toml").write_text("".join(f"{a} = {b}\n" for a, b in p.items()))
    s.update(t_chain=t_chain, block_at_session=int(block["number"], 16), newKey=new_key, recoveryNonce=rn, sessionTag=tag, sid=sid,
             notBefore=not_before, valid_at=valid_at, deadline=deadline, ctx=ctx, popNonce=pop, cred_exp=valid_at + CRED_LIFE)
    save(work, s)
    print(json.dumps({k: s[k] for k in ("t_chain", "newKey", "recoveryNonce", "notBefore", "valid_at", "deadline", "ctx", "popNonce")}, indent=1))


def blob(b):
    return len(b).to_bytes(32, "big") + b + b"\0" * (-len(b) % 32)


def bundle_bytes(fx):
    parts = [(fx / p).read_bytes() for p in ("A/proof", "A/public_inputs", "B/proof", "B/public_inputs",
                                             "pair/proof", "pair/public_inputs", "A/ccsig", "B/ccsig")]
    tails, off, heads = [], 8 * 32, []
    for i, b in enumerate(parts):
        t = (len(b) // 32).to_bytes(32, "big") + b if i in (1, 3, 5) else blob(b)
        heads.append(off.to_bytes(32, "big"))
        tails.append(t)
        off += len(t)
    return (32).to_bytes(32, "big") + b"".join(heads) + b"".join(tails)


def bundle(work, enclave, fx):
    s = state(work)
    fx = pathlib.Path(fx)
    pem = str(pathlib.Path(enclave) / "keys/issuer_dev.pem")
    nonce = bytes.fromhex(s["popNonce"][2:])
    for role in "AB":
        pub = (fx / role / "public_inputs").read_bytes()
        w = [pub[i:i + 32] for i in range(0, len(pub), 32)]
        assert w[0][16:] + w[1][16:] == nonce
        msg = b"POPCC1" + nonce + bytes([int.from_bytes(w[2], "big")]) + role.encode() + w[4]
        assert len(msg) == 72
        (fx / role / "ccsig").write_bytes(issuer_sign(pem, msg))
    b = bundle_bytes(fx)
    (pathlib.Path(work) / "bundle.hex").write_text("0x" + b.hex())
    sel = bytes.fromhex(cast("sig", "verifyPresence(bytes32,uint256,uint256,uint256,uint256,uint64,uint256,bytes)")[2:])
    ix, iy = int(s["cfg"][4]), int(s["cfg"][5])
    head = [int(s["popNonce"], 16), int(s["deviceA"], 16), int(s["qx"], 16), ix, iy, s["notBefore"], s["deadline"], 8 * 32]
    data = sel + b"".join(x.to_bytes(32, "big") for x in head) + blob(b)
    r = rpc("eth_call", {"to": s["adapter"], "data": "0x" + data.hex(), "gas": hex(16_000_000)}, "latest")
    print("bundle bytes", len(b), "eth_call at adapter:", r.get("result") or r.get("error"))
    assert r.get("result", "").startswith("0x7dd7b02c"), r


if __name__ == "__main__":
    {"deploy": deploy, "session": session, "bundle": bundle}[sys.argv[1]](*sys.argv[2:])
