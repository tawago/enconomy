#!/usr/bin/env python3
"""POPCC1 signatures for the field fixture. Local only: python3 -I sign_popcc1.py <issuer pem>.
msg = "POPCC1" || nonce 32 || attempt u8 || 'A'|'B' || code_commit 32 (72 B). sha256, P-256, raw r||s, low-S.
Writes forge/fixtures/field_180ca04b/{A,B}/ccsig. Never writes or prints the key."""
import pathlib, subprocess, sys, tempfile

N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
FX = pathlib.Path(__file__).parent / "forge/fixtures/field_180ca04b"
pem = sys.argv[1]


def der_rs(der):
    assert der[0] == 0x30 and der[2] == 0x02
    rl = der[3]
    r = int.from_bytes(der[4:4 + rl], "big")
    assert der[4 + rl] == 0x02
    return r, int.from_bytes(der[6 + rl:6 + rl + der[5 + rl]], "big")


for role in "AB":
    pub = (FX / role / "public_inputs").read_bytes()
    w = [pub[i:i + 32] for i in range(0, len(pub), 32)]
    nonce = w[0][16:] + w[1][16:]
    attempt = int.from_bytes(w[2], "big")
    msg = b"POPCC1" + nonce + bytes([attempt]) + role.encode() + w[4]
    assert len(msg) == 72
    with tempfile.TemporaryDirectory() as d:
        m, s = pathlib.Path(d, "m"), pathlib.Path(d, "s")
        m.write_bytes(msg)
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem, "-out", str(s), str(m)], check=True)
        r_, s_ = der_rs(s.read_bytes())
    was_high = s_ > N // 2
    if was_high:
        s_ = N - s_
    (FX / role / "ccsig").write_bytes(r_.to_bytes(32, "big") + s_.to_bytes(32, "big"))
    print(role, "signed, flipped to low-S" if was_high else "signed, already low-S")
