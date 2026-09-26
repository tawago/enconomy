"""GET /v1/session/{sid}/attestation (worldid spec 01 §8.1, §8.4; SAFE additions spec 02 §7.3 S4.5).

Public, by sid only, for sessions with a context (safe-tx, test). Signs once, on the first GET after NEAR, and
caches s["att"] so later reads return identical bytes (ECDSA is randomized). Refusals are not cached (a restart
with a fixed POP_UNATTESTED_ALLOW can still sign). No await in here: load -> check -> save is atomic.
"""
from __future__ import annotations

import hashlib

from pop import attest, consumers
from pop.errors import PopError
from pop.human import both_verified

ROLES = ("A", "B")
PROD_TAGS = (b"pop-safe-v2", b"pop-pool-v1")
HUMAN_FIELDS = ("status", "environment", "nullifier", "signal_hash", "rp_nonce", "expires_at_min",
                "issuer_schema_id", "proof")


def _hex0x(h: str | None) -> str | None:
    return None if h is None else (h if h.startswith("0x") else "0x" + h)


def dev_hash(pub_hex: str) -> bytes:
    return hashlib.sha256(bytes.fromhex(pub_hex.removeprefix("0x"))).digest()


def refusal(s: dict, kind, cfg, store) -> str | None:
    """01 §8.1, in order. None = sign."""
    res = s.get("result") or {}
    if s["state"] != "done" or res.get("verdict") != "NEAR":
        return "not_near"
    ctx = s.get("context")
    if not ctx or kind is None:
        return "no_context"
    try:
        if kind.validate(ctx) != bytes.fromhex(ctx["ctx_hash"][2:]):
            return "context_mismatch"
    except (PopError, KeyError, TypeError, ValueError):
        return "context_mismatch"
    h = s.get("human")
    if not both_verified(h) or not h.get("pair_tag"):
        return "human_missing"
    if kind.TAG in PROD_TAGS and any((h[r].get("environment") != "production") for r in ROLES):
        return "nonprod_humans"       # fake / staging / sandbox humans never reach a real consumer
    allow = cfg.unattested_allow
    for r in ROLES:
        d = (res.get("devices") or {}).get(r)
        if not d or not d.get("pubkey"):
            return "unattested_device"
        if not d.get("attested") and d["device_id"] not in allow:
            return "unattested_device"
    if ctx.get("chain_id") != cfg.chain_id:
        return "bad_chain"
    return None


def sign(s: dict, kind, cfg, key) -> dict:
    res = s["result"]
    dev_a, dev_b = (dev_hash(res["devices"][r]["pubkey"]) for r in ROLES)
    expiry = (s["finished_ms"] // 1000) + cfg.att_ttl_s
    d = kind.digest(s, dev_a, dev_b, expiry)
    r, sig_s = attest.sign(key, d)
    pair = s["human"]["pair_tag"]
    return {"v": kind.TAG.decode(), "pair_tag": pair, "dev_a": "0x" + dev_a.hex(), "dev_b": "0x" + dev_b.hex(),
            "expiry": expiry, "digest": "0x" + d.hex(), "r": "0x" + r.hex(), "s": "0x" + sig_s.hex(),
            "tail_hex": "0x" + attest.tail(pair, dev_a, dev_b, expiry, r, sig_s).hex()}


def body(sessions, store, cfg, key, sid: str) -> dict:
    s = sessions.load(sid)
    ctx = s.get("context")
    kinds = consumers.kinds(cfg.test_kinds)
    if not ctx:
        raise PopError(404, "no_context", "attestations exist only for sessions with a context")
    kind = kinds.get(ctx.get("kind"))
    base = {"v": 1, "session_id": s["session_id"], "state": s["state"]}
    if s["state"] != "done":
        return {**base, "verdict": None, "att": None, "att_refused": None}
    att, refused = s.get("att"), None
    if att is None:
        refused = refusal(s, kind, cfg, store)
        if refused is None:
            att = sign(s, kind, cfg, key)
            s["att"] = att
            sessions._save(s)
    res = s["result"] or {}
    h = res.get("human") or {}
    out = {
        **base, "verdict": res.get("verdict"), "reason": res.get("reason"), "attempt": res.get("attempt"),
        "finished_at_s": (s.get("finished_ms") or 0) // 1000, "flight_cm": res.get("flight_cm"),
        "context": ctx, "not_before": s.get("not_before"), "session_nonce": _hex0x(s.get("nonce_hex")),
        "human": {"policy": (s.get("policy") or {}).get("human"),
                  "action": (h.get("A") or {}).get("action"), "rp_id": cfg.worldid_rp_id,
                  **{r: {k: (h.get(r) or {}).get(k) for k in HUMAN_FIELDS} for r in ROLES},
                  "pair_tag": h.get("pair_tag")},
        "devices": {r: {"device_id": d["device_id"], "device_hash": "0x" + dev_hash(d["pubkey"]).hex(),
                        "pubkey": _hex0x(d["pubkey"]), "attested": d.get("attested"),
                        "platform": (store.get_device(d["device_id"]) or {}).get("platform"),
                        "security_level": d.get("security_level")}
                    for r, d in (res.get("devices") or {}).items()},
        "transcripts": res.get("transcripts") or {},
        "zk": res.get("zk"),
        "att": att, "att_refused": refused,
    }
    if ctx.get("kind") == "safe-tx":
        sigs = (s.get("safe") or {}).get("owner_sigs") or {}
        show = att is not None and res.get("verdict") == "NEAR"      # 02 §7.3 S4.5, §11 6b
        out["safe"] = {"owner_sigs": {r: (sigs.get(r) if show else None) for r in ROLES}}
    return out
