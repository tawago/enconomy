"""SAFE consumer (worldid spec 02 §7.1-§7.2): context.safe_tx -> safeTxHash (EIP-712, Safe >= 1.3), allowlist.

ctx_hash = safeTxHash on context.chain_id for the Safe context.consumer. The route checks chain_id == POP_CHAIN_ID
(Ethereum Sepolia 11155111) before this runs; validate() itself only recomputes and applies the allowlist.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from pop import attest
from pop.errors import PopError
from pop.popctx import keccak

KIND = "safe-tx"
TAG = b"pop-safe-v2"
OWNER_MSG_TAG = b"pop-safe-owner-v1"

SAFE_TX_TYPEHASH = bytes.fromhex("bb8310d486368db6bd6f849402fdd73ad53d316b5a4b2644ad6efe0f941286d8")
DOMAIN_TYPEHASH = bytes.fromhex("47e79534a245952e8b16893a336b85a3d9ea9fa8c573f3d803afb92a79469218")
ZERO20 = bytes(20)

# ERC-20s the allowlist accepts, per chain (symbol()/decimals() checked with cast).
TOKENS: dict[int, dict[str, tuple[str, int]]] = {
    480: {"0x2cfc85d8e48f8eab294be644d9e25c3030863003": ("WLD", 18),       # spec vectors (World Chain)
          "0x79a02482a880bce3f13e09da970dc34db4cd24d1": ("USDC", 6)},
    11155111: {"0x1c7d4b196cb0c7b01d743fbc6116a902379c7238": ("USDC", 6)},  # Circle USDC, Ethereum Sepolia
}

ADDR = re.compile(r"^0x[0-9a-f]{40}$")
DATA = re.compile(r"^0x(?:[0-9a-f]{2})*$")
DEC = re.compile(r"^(0|[1-9][0-9]{0,77})$")
ADDR_F = ("to", "gas_token", "refund_receiver")
DEC_F = ("value", "safe_tx_gas", "base_gas", "gas_price", "nonce")
KEYS = set(ADDR_F) | set(DEC_F) | {"data", "operation"}
TRANSFER = bytes.fromhex("a9059cbb")


def _bad(field: str) -> PopError:
    return PopError(400, "bad_context", field)


def _refuse(reason: str) -> PopError:
    return PopError(400, "context_refused", reason)


def _u(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _w(a: bytes) -> bytes:
    return a.rjust(32, b"\0")


def parse_safe_tx(t) -> SimpleNamespace:
    """Strict: exactly the 10 keys, lowercase hex, canonical decimals, operation a JSON int 0|1."""
    if not isinstance(t, dict) or set(t) != KEYS:
        raise _bad("safe_tx_keys")
    out: dict = {}
    for f in ADDR_F:
        if not isinstance(t[f], str) or not ADDR.match(t[f]):
            raise _bad(f)
        out[f] = bytes.fromhex(t[f][2:])
    for f in DEC_F:
        if not isinstance(t[f], str) or not DEC.match(t[f]) or int(t[f]) >= 2 ** 256:
            raise _bad(f)
        out[f] = int(t[f])
    if not isinstance(t["data"], str) or not DATA.match(t["data"]):
        raise _bad("data")
    out["data"] = bytes.fromhex(t["data"][2:])
    if type(t["operation"]) is not int or t["operation"] not in (0, 1):
        raise _bad("operation")
    out["operation"] = t["operation"]
    return SimpleNamespace(**out)


def safe_tx_hash(chain_id: int, safe20: bytes, t: SimpleNamespace) -> bytes:
    ds = keccak(DOMAIN_TYPEHASH + _u(chain_id) + _w(safe20))
    sh = keccak(SAFE_TX_TYPEHASH + _w(t.to) + _u(t.value) + keccak(t.data) + _u(t.operation) + _u(t.safe_tx_gas)
                + _u(t.base_gas) + _u(t.gas_price) + _w(t.gas_token) + _w(t.refund_receiver) + _u(t.nonce))
    return keccak(b"\x19\x01" + ds + sh)


def allowlist(chain_id: int, safe20: bytes, t: SimpleNamespace) -> dict:
    """§7.2, check order: delegatecall, gas_refund_fields, self_call, value_with_call, then case match.
    -> {"case": "native"|"erc20", ...} or raises 400 context_refused."""
    if t.operation != 0:
        raise _refuse("delegatecall")
    if t.safe_tx_gas or t.base_gas or t.gas_price or t.gas_token != ZERO20 or t.refund_receiver != ZERO20:
        raise _refuse("gas_refund_fields")
    if t.to == safe20:
        raise _refuse("self_call")
    if t.value > 0 and t.data:
        raise _refuse("value_with_call")
    if not t.data and t.value > 0:
        return {"case": "native", "to": "0x" + t.to.hex(), "wei": str(t.value)}
    tok = TOKENS.get(chain_id, {}).get("0x" + t.to.hex())
    if (tok and t.value == 0 and len(t.data) == 68 and t.data[:4] == TRANSFER and t.data[4:16] == bytes(12)
            and int.from_bytes(t.data[36:68], "big") > 0):
        return {"case": "erc20", "token": tok[0], "decimals": tok[1], "to": "0x" + t.data[16:36].hex(),
                "amount": str(int.from_bytes(t.data[36:68], "big"))}
    raise _refuse("unknown_call")


def validate(context: dict) -> bytes:
    """-> ctx_hash (the recomputed safeTxHash) or raises PopError (bad_context / context_refused / context_mismatch)."""
    t = parse_safe_tx(context.get("safe_tx"))
    safe20 = bytes.fromhex(context["consumer"][2:])
    allowlist(context["chain_id"], safe20, t)
    h = safe_tx_hash(context["chain_id"], safe20, t)
    if h != bytes.fromhex(context["ctx_hash"][2:]):
        raise PopError(400, "context_mismatch", "ctx_hash != safeTxHash(safe_tx)")
    return h


def digest(s: dict, dev_a: bytes, dev_b: bytes, expiry: int) -> bytes:
    c = s["context"]
    return attest.tagged_digest(TAG, c["chain_id"], c["consumer"], c["ctx_hash"], s["human"]["pair_tag"],
                                dev_a, dev_b, expiry)


def owner_message(ctx_hash: bytes) -> bytes:
    """What each phone signs at Confirm (P256Owner): "pop-safe-owner-v1" || safeTxHash, SHA256withECDSA."""
    return OWNER_MSG_TAG + ctx_hash
