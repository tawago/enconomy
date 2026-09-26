import hashlib, sys
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes
k = ec.derive_private_key(0xC0FFEE, ec.SECP256R1())
pub = k.public_key().public_numbers()
chain, pool = int(sys.argv[1]), bytes.fromhex(sys.argv[2][2:])
leaf = 11011320419327886381298776674271937664568292783180157783978689262892574625042
pair = bytes.fromhex("33"*32); expiry = 1790000000
pre = b"pop-pool-v1" + chain.to_bytes(32,"big") + pool + leaf.to_bytes(32,"big") + pair + expiry.to_bytes(8,"big")
assert len(pre) == 135
d = hashlib.sha256(pre).digest()
r, s = utils.decode_dss_signature(k.sign(d, ec.ECDSA(utils.Prehashed(hashes.SHA256()))))
print(hex(pub.x), hex(pub.y), "0x"+d.hex(), "0x%064x"%r, "0x%064x"%s)
