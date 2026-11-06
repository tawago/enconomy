"""Python and Solidity must agree on these bytes: a mismatch only shows up as a revert on chain."""
from __future__ import annotations

import pytest

from backend.attester import tagged_digest
from backend.safe_tx import TAG, parse_safe_tx, safe_tx_hash
from tests.helpers import tx

SAFE480 = "0x3fad7600f309b0c3d60a57023b0262460b0603dc"
WLD = "0x2cfc85d8e48f8eab294be644d9e25c3030863003"
USDC480 = "0x79a02482a880bce3f13e09da970dc34db4cd24d1"
MSCO = "0xa83c336b20401af773b6219ba5027174338d1836"


def word(a: str) -> str:
    return a[2:].rjust(64, "0")


ROW = {
    1: (480, tx(value=str(10 ** 16)), "0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5"),
    2: (480, tx(value="0", to=WLD, data="0xa9059cbb" + word("0x" + "22" * 20) + "%064x" % (15 * 10 ** 17)),
        "0x320418179acf57e8607ddcb3f82e113cb45d0d7579b95ccb81ee04afc056a3ce"),
    3: (480, tx(value="0", to=SAFE480, data="0xe19a9dd9" + word("0x" + "33" * 20)),
        "0x29e1fbc2114cbf3e89bf83db0a08b3faf7b502b2fc6d60691e0fcf132df7c2f7"),
    4: (480, tx(nonce="42", to=MSCO, value="123456789", data="0xdeadbeef00", operation=1, safe_tx_gas="50000",
                base_gas="21000", gas_price="7", gas_token=USDC480, refund_receiver="0x" + "44" * 20),
        "0x321d09105a40b0d115e6f2b294208a0fac9eb117f88c3d7ca5e036484aa591e1"),
}
ROW[5] = (4801, ROW[4][1], "0xb0bcdc64af0c7fe223a8b673357104673dc659be0b9c98a9970d932a3c8cb2ac")


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_safe_tx_hash_vectors(n):
    chain, t, h = ROW[n]
    assert "0x" + safe_tx_hash(chain, bytes.fromhex(SAFE480[2:]), parse_safe_tx(t)).hex() == h


def test_digest_matches_solidity():
    """contracts/test/PopCtx.t.sol test_attest_digest_vector."""
    b32 = lambda n: n.to_bytes(32, "big")
    d = tagged_digest(TAG, 480, "0x" + "11" * 20, b32(0x22), b32(0x33), b32(0x44), b32(0x55), 1790000000)
    assert d.hex() == "923a0f96071090da810c42c7f0c43c56fefd454497a45fcde7138b1a45829720"
