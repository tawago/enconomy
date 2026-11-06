"""Stdlib-only checks for notes/eip8141-family.md.

1. Pure-python keccak256; reproduce the EIP-8272 reference vector.
2. P-256 hardware-key question: the app signs with SHA256withECDSA
   (message mode). EIP-8141's native P256 scheme verifies
   P256VERIFY(msg=sig_hash, ...). Show that a message-mode signature over
   sig_hash fails there and passes against sha256(sig_hash); show low-s
   normalization; derive the P256 signer address keccak(qx||qy)[12:].
3. Gas arithmetic for a few frame-tx shapes against MAX_VERIFY_GAS.

Run: python3 -I eip8141_poc.py
"""
import hashlib
import secrets

# ---------- keccak256 (Keccak-f[1600], original padding 0x01) ----------
RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
      0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
      0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
      0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
      0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
      0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
       [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
M64 = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & M64 if n else x


def _f(A):
    for rc in RC:
        C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
        D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        A = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
        B = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], ROT[x][y])
        A = [[B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        A[0][0] ^= rc
    return A


def keccak256(data: bytes) -> bytes:
    rate = 136
    p = bytearray(data) + b"\x01"
    while len(p) % rate:
        p += b"\x00"
    p[-1] |= 0x80
    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(p), rate):
        blk = p[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            A[x][y] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        A = _f(A)
    out = b"".join(A[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out


assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"

# ---------- 1. EIP-8272 reference vector ----------
ENTRY_DOMAIN = keccak256(b"RECENT_ROOT_ENTRY")
STORAGE_DOMAIN = keccak256(b"RECENT_ROOT_STORAGE")
src = bytes.fromhex("0000000000000000000000000000000000000001")
salt = b"\x00" * 32
source_id = keccak256(src + salt)
slot = 1
root = (2).to_bytes(32, "big")
entry_hash = keccak256(ENTRY_DOMAIN + source_id + slot.to_bytes(8, "big") + root)
storage_key = keccak256(STORAGE_DOMAIN + source_id + (slot % 8192).to_bytes(8, "big"))
print("[8272] ENTRY_DOMAIN  ", ENTRY_DOMAIN.hex())
print("[8272] STORAGE_DOMAIN", STORAGE_DOMAIN.hex())
print("[8272] source_id     ", source_id.hex())
print("[8272] entry_hash    ", entry_hash.hex())
print("[8272] storage_key   ", storage_key.hex())
assert source_id.hex() == "b9382d35273c75a50631a3e84d3c75ec9266e2b18c35a627e16cdbf26a18ca85"
assert entry_hash.hex() == "0a0d1254c851be5a133b4c9a9e300f5602fc0f43dbe65aa6a66930d4ca0a51b8"
assert storage_key.hex() == "5f027aa1cbe2df279bf6518edd4b44ea5409fd800189ec35224e10ab05e574c3"
# the two domain constants appear as PUSH32 immediates in RECENT_ROOT_CODE
RRC = ("8f42481679c8e6fefa040974b3c905e0ce3f2e464ba93acdb074a41181617efc",
       "bdc897da2177d260ff5f4be5d4b2aad43f89c3347a305b584fa5a2546d053daa")
print("[8272] domains match PUSH32s in RECENT_ROOT_CODE:",
      sorted(RRC) == sorted([ENTRY_DOMAIN.hex(), STORAGE_DOMAIN.hex()]))
print("[8272] reference vector reproduced: OK")

# ---------- 2. P-256 ----------
p = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
a = p - 3
b = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
n = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
     0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def add(P, Q):
    if P is None:
        return Q
    if Q is None:
        return P
    if P[0] == Q[0] and (P[1] + Q[1]) % p == 0:
        return None
    if P == Q:
        l = (3 * P[0] * P[0] + a) * pow(2 * P[1], -1, p) % p
    else:
        l = (Q[1] - P[1]) * pow(Q[0] - P[0], -1, p) % p
    x = (l * l - P[0] - Q[0]) % p
    return (x, (l * (P[0] - x) - P[1]) % p)


def mul(k, P):
    R = None
    while k:
        if k & 1:
            R = add(R, P)
        P = add(P, P)
        k >>= 1
    return R


def sign_digest(d, z: bytes):
    e = int.from_bytes(z, "big")
    while True:
        k = secrets.randbelow(n - 1) + 1
        r = mul(k, G)[0] % n
        s = pow(k, -1, n) * (e + r * d) % n
        if r and s:
            return r, s


def verify_digest(Q, z: bytes, r, s):  # what P256VERIFY(msg=z,...) does
    if not (0 < r < n and 0 < s < n):
        return False
    e = int.from_bytes(z, "big")
    w = pow(s, -1, n)
    X = add(mul(e * w % n, G), mul(r * w % n, Q))
    return X is not None and X[0] % n == r


d = secrets.randbelow(n - 1) + 1
Q = mul(d, G)
qx, qy = Q[0].to_bytes(32, "big"), Q[1].to_bytes(32, "big")
signer_addr = keccak256(qx + qy)[12:]
print("[p256] signer address keccak(qx||qy)[12:] =", "0x" + signer_addr.hex())

sig_hash = keccak256(b"stand-in for compute_sig_hash(tx)")
# Message mode (SHA256withECDSA / kSecKeyAlgorithmECDSASignatureMessageX962SHA256):
r, s = sign_digest(d, hashlib.sha256(sig_hash).digest())
print("[p256] message-mode sig verifies vs msg=sig_hash        :", verify_digest(Q, sig_hash, r, s))
print("[p256] message-mode sig verifies vs msg=sha256(sig_hash):", verify_digest(Q, hashlib.sha256(sig_hash).digest(), r, s))
# Digest mode (NONEwithECDSA / ...DigestX962SHA256): sign the 32 bytes as-is
r2, s2 = sign_digest(d, sig_hash)
print("[p256] digest-mode sig verifies vs msg=sig_hash         :", verify_digest(Q, sig_hash, r2, s2))
# low-s: EIP-8141 rejects s > n/2; (r, n-s) is the same signature, normalised
high = s2 > n // 2
s2n = n - s2 if high else s2
print("[p256] raw s was high:", high, "| normalised s passes low-s and verifies:",
      s2n <= n // 2 and verify_digest(Q, sig_hash, r2, s2n))

# ---------- 3. gas arithmetic ----------
FRAME_TX_INTRINSIC_COST, PER_FRAME = 12000, 475
MAX_VERIFY_GAS = 100_000


def tokens(data: bytes):
    z = data.count(0)
    return z + (len(data) - z) * 4


print("\n[gas] scheme costs: SECP256K1 2800, P256 6700, ARBITRARY 100 (+data)")
# P256 sig entry: signer 20 B (non-zero), msg empty, signature 128 B priced as all non-zero (elided)
p256_entry = 4 * tokens(b"\x11" * 20) + 4 * (128 * 4) + 6700
arb_entry = 4 * (128 * 4) + 100  # ARBITRARY, 128 B witness (r||s||qx||qy), elided
print("[gas] P256 signature entry intrinsic ~", p256_entry)
print("[gas] ARBITRARY 128 B entry intrinsic ~", arb_entry,
      "+ in-EVM: SHA256 precompile ~72 + P256VERIFY 6900 + SLOADs/calls")
# keyed nonce (EIP-8250): per key 12100 execution (intrinsic) + 97920 state gas on first use
print("[gas] keyed nonce per key: 12100 exec (intrinsic) + 97920 state on first use;",
      "state gas is outside MAX_VERIFY_GAS but inside MAX_VERIFY_STATE_GAS=500000 ->",
      500000 // 97920, "fresh keys max per tx in public mempool (16 protocol max)")
# ZK verifier inside VERIFY
for name, g in [("UltraHonk verify, measured in repo (opt3 half)", 2_774_790),
                ("Groth16 verifyProof, measured in repo (opt2)", 228_804),
                ("single P256VERIFY", 6900)]:
    print(f"[gas] {name}: {g} -> public mempool OK? {g < MAX_VERIFY_GAS}")
