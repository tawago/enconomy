"""Compare the Lean copy of the byte layout with the real codec.py, on four samples.

Usage, from fv/v1/server, with the server folder on the path:
  python spec-checks/layout_vectors.py <lean build log>

The log holds the Lean '#eval' lines 'LAYOUT <name> <hex>'. This only compares bytes on these samples.
It proves nothing about the codec. It says nothing about the air (CN1).
"""
import re
import sys

from pop import codec


def tx(v):
    t = dict(role="A", attempt=1, nonce=bytes([7]) * 32, pk_self=bytes([1]) * 65, pk_partner=bytes([2]) * 65,
             sample_rate=48000, half=-5, play_frame_position=1000, play_nano_time=2000000000,
             rec_frame0_nano_time=3000000000, self_os_delta=-77, commit_hash=bytes([4]) * 32)
    t["rec_sha256" if v == 1 else "rec_root"] = bytes([9]) * 32
    if v == 2:
        t.update(version=2, a_self=70000, p_partner=80000, delta=96, code_commit=bytes([6]) * 32)
    return t


want = {
    "commit1": codec.encode_commit("B", 3, bytes([7]) * 32, bytes([9]) * 32, 1),
    "commit2": codec.encode_commit("B", 3, bytes([7]) * 32, bytes([9]) * 32, 2),
    "tx1": codec.encode_transcript(tx(1)),
    "tx2": codec.encode_transcript(tx(2)),
}
got = dict(re.findall(r"LAYOUT (\w+) ([0-9a-f]+)", open(sys.argv[1]).read()))
bad = 0
for name, raw in want.items():
    same = got.get(name) == raw.hex()
    bad += not same
    print(f"{name}: {len(raw)} bytes, Lean {'same' if same else 'DIFFERENT'}")
    assert codec.decode_commit(raw) if name.startswith("commit") else codec.decode_transcript(raw)

# The real codec holds widths fixed too: struct cuts a long nonce, it can't carry 33 bytes.
c = codec.decode_commit(codec.encode_commit("A", 0, bytes([7]) * 33, bytes([9]) * 32, 1))
print("33-byte nonce in, width out:", len(c["nonce"]))
for n in (70, 72):
    try:
        codec.decode_commit(bytes(n))
        print(f"commit of {n} bytes: accepted")
        bad += 1
    except ValueError:
        print(f"commit of {n} bytes: refused")
print("rc", bad)
sys.exit(bad)
