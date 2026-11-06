"""EVP recovery backend. Behind web/serve.mjs at https://recover.tawago.test/v1/recovery/*. Holds L's test key (.env)."""
import base64
import json
import os
import subprocess
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.chain import CORE, DEPLOY, HERE, RUN, SIDECAR, EMAIL, ORIGIN, call, cast, get_json, l_key, send

app = FastAPI(title="evp-recovery")
START = RUN / "start.json"
WINDOW_S = 900


def deploy() -> dict:
    return json.loads(DEPLOY.read_text())


def hex32(v: str) -> str:
    return "0x" + v.lower().removeprefix("0x").rjust(64, "0")


class StartIn(BaseModel):
    qx: str
    qy: str


class SubmitIn(BaseModel):
    session_id: str
    token: str
    not_before: int | None = None   # the bundle has them, accepted for the page's convenience
    sid: str | None = None
    simulate: bool = False


@app.post("/v1/recovery/start")
def start(b: StartIn):
    d = deploy()
    qx, qy = hex32(b.qx), hex32(b.qy)
    new_key = "0x" + cast("keccak", cast("abi-encode", "c(uint256,uint256)", qx, qy))[-40:]
    nonce = int(call(d["account"], "recoveryNonce()(uint256)"))
    tag = "0x" + os.urandom(32).hex()
    deadline = int(time.time()) + WINDOW_S
    ctx = call(d["account"], "evpCtx(address,bytes32,uint256)(bytes32)", new_key, tag, deadline)
    s = {"qx": qx, "qy": qy, "newKey": new_key, "recoveryNonce": nonce, "sessionTag": tag, "deadline": deadline, "ctx": ctx}
    START.write_text(json.dumps(s, indent=1))
    return {"ctx": ctx, "evpNonce": ctx, "deadline": deadline, "sessionTag": tag, "newKey": new_key, "recoveryNonce": nonce,
            "context": {"chain_id": 1337, "consumer": d["account"].lower(), "ctx_hash": ctx}}


def offsets(token: str, email: str, aud: str) -> str:
    """offs of EvpCheck.sol: 16 x uint16. contracts/script/mint-fixtures.mjs offsets()."""
    d1 = token.index(".")
    d2 = token.index(".", d1 + 1)
    t = token.index("~")
    k1 = token.index(".", t + 1)
    k2 = token.index(".", k1 + 1)
    dec = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()   # noqa: E731
    ep, kp = dec(token[d1 + 1:d2]), dec(token[k1 + 1:k2])
    f = [d1, d2, t, k1, k2, ep.index('"email":"'), len(email.encode()), ep.index('"email_verified":true'), ep.index('"iat":'),
         ep.index('"x":"'), ep.index('"y":"'), kp.index('"aud":"'), kp.index('"nonce":"'), kp.index('"iat":'),
         kp.index('"sd_hash":"'), len(aud.encode())]
    return hex(sum(v << (16 * i) for i, v in enumerate(f)))


def bundle_hex(b: dict) -> str:
    """abi.encode(EvpNoirPresenceVerifier.Bundle) from the core's /zk/bundle."""
    def raw(h):
        return bytes.fromhex(h.removeprefix("0x"))

    def blob(x):
        return len(x).to_bytes(32, "big") + x + b"\0" * (-len(x) % 32)

    def words(v):
        return len(v).to_bytes(32, "big") + b"".join(raw(w) for w in v)

    p = b["proofs"]
    tails = [blob(raw(p["A"]["proof"])), words(p["A"]["public_inputs"]), blob(raw(p["B"]["proof"])), words(p["B"]["public_inputs"]),
             blob(raw(p["pair"]["proof"])), words(p["pair"]["public_inputs"]),
             blob(raw(b["code_attest"]["A"]["sig_hex"])), blob(raw(b["code_attest"]["B"]["sig_hex"]))]
    off, heads = 8 * 32, []
    for t in tails:
        heads.append(off.to_bytes(32, "big"))
        off += len(t)
    return "0x" + ((32).to_bytes(32, "big") + b"".join(heads) + b"".join(tails)).hex()


def send_start(job: dict) -> dict:
    env = {**os.environ, "EVP_L_KEY": l_key()}
    p = subprocess.run(["node", str(HERE / "backend/send_start.cjs")], input=json.dumps(job), capture_output=True, text=True, env=env)
    if not p.stdout.strip():
        raise HTTPException(502, p.stderr[-1500:].replace(env["EVP_L_KEY"], "<key>"))
    return json.loads(p.stdout)


@app.post("/v1/recovery/submit")
def submit(b: SubmitIn):
    d, s = deploy(), json.loads(START.read_text())
    bundle = get_json(f"{CORE}/v1/session/{b.session_id}/zk/bundle")
    return send_start({"account": d["account"], "cfg": d["cfg"], "laptop": d["laptop"], "qx": s["qx"], "qy": s["qy"],
                       "newKey": s["newKey"], "sessionTag": s["sessionTag"], "deadline": s["deadline"],
                       "notBefore": bundle["not_before"], "sid": bundle["sid"], "bundle": bundle_hex(bundle),
                       "token": "0x" + b.token.encode().hex(), "offs": offsets(b.token, EMAIL, ORIGIN),
                       "sidecar": SIDECAR, "simulate": b.simulate})


@app.post("/v1/recovery/finish")
def finish():
    r = send(l_key(), 250000, deploy()["account"], "finishRotation()")
    return {"tx": r["transactionHash"], "state": state()}


@app.get("/v1/recovery/state")
def state():
    a = deploy()["account"]
    return {"account": a, "owner": call(a, "owner()(address)"), "pendingOwner": call(a, "pendingOwner()(address)"),
            "readyAt": int(call(a, "readyAt()(uint64)")), "recoveryNonce": int(call(a, "recoveryNonce()(uint256)")),
            "now": int(time.time())}
