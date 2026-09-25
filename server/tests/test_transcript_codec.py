import hashlib
import struct

import pytest

from pop.codec import TRANSCRIPT_LEN, decode_commit, decode_transcript, encode_commit, encode_transcript

# known vector; the Kotlin TranscriptCodecTest pins the same sha256
VEC = dict(role="A", attempt=1, nonce=bytes(range(32)), pk_self=b"\x04" + b"\x11" * 64, pk_partner=b"\x04" + b"\x22" * 64,
           sample_rate=48000, half=-45566, rec_sha256=b"\x33" * 32, play_frame_position=26400,
           play_nano_time=123456789012345, rec_frame0_nano_time=123456000000000, self_os_delta=-7,
           commit_hash=b"\x44" * 32)
VEC_SHA = "40e85cdceed6bea79673f2cc017f89b248e9b0e20bbb2fdf88b4d8d3b6756e35"
COMMIT_SHA = "4678fcbfe517fb8c207fe6b01d481632e4d1b4475c4eb11b0455816f0866e9a6"   # ("B", 0, range(32), 0x33*32)


def test_known_vector_and_offsets():
    raw = encode_transcript(VEC)
    assert len(raw) == TRANSCRIPT_LEN == 269
    assert hashlib.sha256(raw).hexdigest() == VEC_SHA
    assert raw[0:4] == b"POPT" and raw[4] == 1 and raw[5] == 0x41 and raw[6] == 1
    assert raw[7:39] == VEC["nonce"] and raw[39:104] == VEC["pk_self"] and raw[104:169] == VEC["pk_partner"]
    assert struct.unpack(">I", raw[169:173])[0] == 48000 and struct.unpack(">i", raw[173:177])[0] == -45566
    assert raw[177:209] == VEC["rec_sha256"]
    assert struct.unpack(">QQQ", raw[209:233]) == (26400, 123456789012345, 123456000000000)
    assert struct.unpack(">i", raw[233:237])[0] == -7 and raw[237:269] == VEC["commit_hash"]
    assert decode_transcript(raw) == VEC


def test_commit_vector():
    c = encode_commit("B", 0, bytes(range(32)), b"\x33" * 32)
    assert len(c) == 71 and hashlib.sha256(c).hexdigest() == COMMIT_SHA
    assert c[:7] == b"POPC\x01B\x00" and decode_commit(c)["rec_sha256"] == b"\x33" * 32


@pytest.mark.parametrize("mut", [lambda r: r[:-1], lambda r: r + b"\0", lambda r: b"POPX" + r[4:],
                                 lambda r: r[:4] + b"\x02" + r[5:], lambda r: r[:5] + b"C" + r[6:]])
def test_decode_rejects(mut):
    with pytest.raises(ValueError):
        decode_transcript(mut(encode_transcript(VEC)))
