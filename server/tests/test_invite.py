import hashlib

import pytest

from pop import invite


def test_roundtrip_layout():
    hint = bytes(range(8))
    b = invite.encode("11" * 16, "22" * 16, 0x01020304, hint)
    assert len(b) == 49 and b[:5] == b"POP1\x01"
    assert b[5:21] == b"\x11" * 16 and b[21:37] == b"\x22" * 16 and b[37:41] == b"\x01\x02\x03\x04" and b[41:] == hint
    d = invite.decode(b)
    assert d == {"session_id": "11" * 16, "join_token": "22" * 16, "expires_at_s": 0x01020304, "host_hint": hint}
    q = invite.to_qr(b)
    assert q.startswith("pop1:") and "=" not in q and len(q) == 5 + 66
    assert invite.from_qr(q) == b


def test_known_vector():
    b = invite.encode("00" * 16, "ff" * 16, 1_790_000_120, b"\xaa" * 8)
    assert hashlib.sha256(b).hexdigest() == hashlib.sha256(
        b"POP1\x01" + b"\x00" * 16 + b"\xff" * 16 + (1_790_000_120).to_bytes(4, "big") + b"\xaa" * 8).hexdigest()


@pytest.mark.parametrize("bad", [b"", b"POP2\x01" + b"\x00" * 44, b"POP1\x02" + b"\x00" * 44, b"POP1\x01" + b"\x00" * 43])
def test_decode_rejects(bad):
    with pytest.raises(ValueError):
        invite.decode(bad)
