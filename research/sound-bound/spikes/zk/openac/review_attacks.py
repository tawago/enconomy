"""Reviewer tamper attacks against the openac circuits. Writes inputs to OUT."""
import copy, hashlib, json, os, struct, sys
OA = "/Users/takahiro_ogawa/dev/enconomy/research/sound-bound/spikes/zk/openac"
ZK = os.path.dirname(OA)
sys.path.insert(0, OA); sys.path.insert(0, os.path.join(ZK, "enclave"))
import prep_inputs as P
from common import transcript, credential
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
fxl = lambda s: json.load(open(os.path.join(ZK, "fixtures", s + ".json")))

def dump(name, inp, exp, note):
    json.dump(inp, open(f"{OUT}/{name}.input.json", "w"))
    json.dump({"public": exp, "info": {"note": note}}, open(f"{OUT}/{name}.public.json", "w"))
    print(name, "|", note)

# 1. swap roles on the touch fixture: swapped d = -22 (-7.9 cm) is INSIDE the bounds, so only the
#    role byte / crossed-pub signatures can stop it (the builder's swap test on 180ca04b gives d=-93,
#    which the -20 cm bound rejects on its own).
inp, exp, _ = P.build(fxl("2dc2eb59"), "pair_v1", "A", "swap")
dump("atk_swap_touch", inp, exp, "2dc2eb59 halves/sigs swapped A<->B, d=-22 within bounds")

# 2. cross-session splice: A slot from 180ca04b, B slot from b550cf12 (both NEAR), nonce of 180ca04b.
a = fxl("180ca04b"); b = fxl("b550cf12")
m = copy.deepcopy(a); m["roles"]["B"] = b["roles"]["B"]
inp, exp, _ = P.build(m, "pair_v1", "A")
dump("atk_splice", inp, exp, "A from 180ca04b + B from b550cf12, nonce 180ca04b")

# 3. shift both halves by +1000 (d unchanged) without re-signing
inp, exp, _ = P.build(fxl("2dc2eb59"), "pair_v1", "A")
for k in ("halfA", "halfB"):
    v = struct.unpack(">i", bytes(inp[k]))[0] + 1000
    inp[k] = list(struct.pack(">i", v))
dump("atk_shift_both", inp, exp, "both halves +1000 samples, d unchanged, not re-signed")

# 4. FAR fixture (200 cm), prover widens dHi to 10^6 samples in its witness
inp, exp, _ = P.build(fxl("9afb91c6"), "pair_v1", "A")
inp["dHi"] = str(10**6)
dump("atk_wide_bounds", inp, exp, "9afb91c6 (211 cm) with prover-chosen dHi=1e6; expected public keeps honest dHi")
exp2 = list(exp); exp2[8] = str(10**6)
json.dump({"public": exp2, "info": {"note": "naive verifier that echoes the proof's dHi"}}, open(f"{OUT}/atk_wide_bounds_naive.public.json", "w"))

# 5. v2: holder A's secret but claims me=1 (B's credential)
inp, exp, _ = P.build(fxl("180ca04b"), "pair_v2", "A")
inp["me"] = "1"
dump("atk_v2_me_flip", inp, exp, "holder A secret, me=1 (points at B's commit)")

# 6. SELF-PAIRING: one credentialed key signs BOTH roles (own = partner = same pub).
#    Throwaway dev device key generated here; credential issued with the throwaway dev issuer key.
with open(os.path.join(ZK, "enclave", "keys", "issuer_dev.pem"), "rb") as f:
    isk = serialization.load_pem_private_key(f.read(), None)
dk = ec.generate_private_key(ec.SECP256R1())
pn = dk.public_key().public_numbers()
pub = pn.x.to_bytes(32, "big") + pn.y.to_bytes(32, "big")
base = fxl("180ca04b")
nonce = bytes.fromhex(base["nonce_hex"]); sr = base["sr"]; att = base["attempt"]
expiry = base["roles"]["A"]["cred_expiry_unix"]
sign = lambda sk, msg: decode_dss_signature(sk.sign(hashlib.sha256(msg).digest(), ec.ECDSA(Prehashed(hashes.SHA256()))))
cr, cs = sign(isk, credential(pub, expiry))
fx = copy.deepcopy(base); fx["session_id"] = "selfpair-dev"
halves = {"A": 45010, "B": 45000}   # d = 10 -> 3.6 cm, NEAR
for r in "AB":
    rr = fx["roles"][r]
    rec = hashlib.sha256(b"fake-rec" + r.encode()).digest()
    ts = [1790000000000000000]
    tr = transcript(nonce, att, r, pub, pub, sr, halves[r], rec, ts)
    sr_, ss_ = sign(dk, tr)
    rr.update({"device_pub_x": pub[:32].hex(), "device_pub_y": pub[32:].hex(), "half_samples": halves[r],
               "rec_hash_hex": rec.hex(), "os_ts": ts, "sig_r_hex": f"{sr_:064x}", "sig_s_hex": f"{ss_:064x}",
               "cred_sig_r_hex": f"{cr:064x}", "cred_sig_s_hex": f"{cs:064x}", "cred_expiry_unix": expiry})
inp, exp, info = P.build(fx, "pair_v1", "A")
dump("atk_selfpair", inp, exp, f"one dev key signs role A and role B (pubA == pubB), d={info['d_samples']}")
