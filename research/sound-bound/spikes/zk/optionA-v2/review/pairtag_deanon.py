"""pairTag = Poseidon7(TAG_PAIR; nonce, xA, xB) is computable by anyone who knows the public nonce and a list
of device public keys (the issuer enrolled all of them). Recover who met from the public outputs alone."""
import json, secrets, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent / "poseidon7"))
import p7
from common2 import P
fx = json.loads((HERE.parent / "fixtures" / "180ca04b.json").read_text())
nonce = bytes.fromhex(fx["nonce_hex"]); nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
public_tag = int(json.loads((HERE.parent / "inputs" / "180ca04b_d2_A_sig.public.json").read_text())["public"][2])
d = fx["deltas"]["2"]
enrolled = [secrets.randbits(255) % P for _ in range(98)] + [int(d[r]["device_pub_x"], 16) for r in "AB"]
t = time.time(); hits = []; n = 0
for xa in enrolled:
    for xb in enrolled:
        if xa == xb: continue
        n += 1
        if p7.sponge16(7, [nh, nl, xa, xb]) == public_tag: hits.append((hex(xa)[:14], hex(xb)[:14]))
dt = time.time() - t
print(f"{n} candidate pairs of 100 enrolled keys in {dt:.1f} s (pure Python, {n/dt:.0f} Poseidon/s)")
print("match:", hits, " fixture A/B x:", d["A"]["device_pub_x"][:12], d["B"]["device_pub_x"][:12])
