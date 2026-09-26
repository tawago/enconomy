#!/usr/bin/env python3
"""Build bbapi msgpack requests for the iOS harness, and decode its responses.

  zkio.py prep <out_dir>                      -> srs.msgpack, phone.req.msgpack, phone_opt.req.msgpack
  zkio.py decode <resp.msgpack> <out_dir>     -> proof, public_inputs, vk (bb CLI binary format)
Settings match the ZK team's `bb prove -t evm`: oracle_hash_type=keccak, ZK on.
"""
import base64, gzip, json, os, struct, sys

NOIR = os.path.expanduser("~/.enconomy/zk/optA/noir")
CRS = os.path.expanduser("~/.bb-crs/bn254_g1.dat")
G2 = bytes.fromhex(
    "0118c4d5b837bcc2bc89b5b398b5974e9f5944073b32078b7e231fec938883b0"
    "260e01b251f6f1c7e7ff4e580791dee8ea51d87a358e038b4efe30fac09383c1"
    "22febda3c0c0632a56475b4214e5615e11e6dd3f96e6cea2854a87d4dacc5e55"
    "04fc6369f7110fe3d25156c1bb9a72859cf2a04641f99ba4ee413c80da6a5fe4")


def p(o):
    if isinstance(o, bool):
        return b"\xc3" if o else b"\xc2"
    if isinstance(o, int):
        assert 0 <= o < 2**32
        return bytes([o]) if o < 128 else b"\xce" + struct.pack(">I", o)
    if isinstance(o, str):
        b = o.encode()
        return (bytes([0xa0 | len(b)]) if len(b) < 32 else b"\xd9" + bytes([len(b)])) + b
    if isinstance(o, (bytes, bytearray)):
        return b"\xc6" + struct.pack(">I", len(o)) + bytes(o)
    if isinstance(o, list):
        return (bytes([0x90 | len(o)]) if len(o) < 16 else b"\xdc" + struct.pack(">H", len(o))) + b"".join(map(p, o))
    if isinstance(o, dict):
        assert len(o) < 16
        return bytes([0x80 | len(o)]) + b"".join(p(k) + p(v) for k, v in o.items())
    raise TypeError(o)


def cmd(name, body):
    return p([[name, body]])  # args tuple (1 arg) holding NamedUnion [name, {fields}]


def prep(out):
    os.makedirs(out, exist_ok=True)
    g1 = open(CRS, "rb").read()
    n = len(g1) // 64
    open(f"{out}/srs.msgpack", "wb").write(cmd("SrsInitSrs", {"points_buf": g1, "num_points": n, "g2_point": G2}))
    for c in ["phone", "phone_opt"]:
        j = json.load(open(f"{NOIR}/{c}/target/{c}.json"))
        bc = gzip.decompress(base64.b64decode(j["bytecode"]))
        wit = gzip.decompress(open(f"{NOIR}/{c}/target/{c}.gz", "rb").read())
        settings = {"ipa_accumulation": False, "oracle_hash_type": "keccak", "disable_zk": False,
                    "optimized_solidity_verifier": False}
        req = cmd("CircuitProve", {"circuit": {"name": c, "bytecode": bc, "verification_key": b""},
                                   "witness": wit, "settings": settings})
        open(f"{out}/{c}.req.msgpack", "wb").write(req)
        print(c, "bytecode", len(bc), "witness", len(wit), "req", len(req))
    print("srs points", n)


class R:
    def __init__(s, b): s.b, s.i = b, 0
    def u(s, n):
        v = s.b[s.i:s.i + n]; s.i += n; return v
    def read(s):
        t = s.b[s.i]; s.i += 1
        if t < 0x80: return t
        if 0x80 <= t <= 0x8f: return {s.read(): s.read() for _ in range(t & 15)}
        if 0x90 <= t <= 0x9f: return [s.read() for _ in range(t & 15)]
        if 0xa0 <= t <= 0xbf: return s.u(t & 31).decode()
        if t in (0xc2, 0xc3): return t == 0xc3
        if t in (0xc4, 0xc5, 0xc6):
            n = int.from_bytes(s.u({0xc4: 1, 0xc5: 2, 0xc6: 4}[t]), "big"); return bytes(s.u(n))
        if t in (0xd9, 0xda, 0xdb):
            n = int.from_bytes(s.u({0xd9: 1, 0xda: 2, 0xdb: 4}[t]), "big"); return s.u(n).decode()
        if t in (0xdc, 0xdd):
            n = int.from_bytes(s.u(2 if t == 0xdc else 4), "big"); return [s.read() for _ in range(n)]
        if t in (0xde, 0xdf):
            n = int.from_bytes(s.u(2 if t == 0xde else 4), "big"); return {s.read(): s.read() for _ in range(n)}
        if t in (0xcc, 0xcd, 0xce, 0xcf): return int.from_bytes(s.u(1 << (t - 0xcc)), "big")
        raise ValueError(hex(t))


def decode(resp, out):
    name, body = R(open(resp, "rb").read()).read()
    assert name == "CircuitProveResponse", (name, body)
    os.makedirs(out, exist_ok=True)
    open(f"{out}/proof", "wb").write(b"".join(body["proof"]))
    open(f"{out}/public_inputs", "wb").write(b"".join(body["public_inputs"]))
    open(f"{out}/vk", "wb").write(body["vk"]["bytes"])
    print("proof", 32 * len(body["proof"]), "B; public_inputs", 32 * len(body["public_inputs"]), "B; vk",
          len(body["vk"]["bytes"]), "B; vk_hash", body["vk"]["hash"].hex())


if __name__ == "__main__":
    {"prep": prep, "decode": decode}[sys.argv[1]](*sys.argv[2:])
