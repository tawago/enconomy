package com.enconomy.pop.chain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** Server tests/test_safe_tx.py ROW vectors (spec 02 §7.4). */
class SafeTxTest {
    private val safe480 = "0x3fad7600f309b0c3d60a57023b0262460b0603dc"

    @Test fun nativeVector() {
        val t = SafeTx(to = "0x" + "11".repeat(20), value = "10000000000000000")
        assertEquals("0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5", SafeTx.hashHex(480, safe480, t))
    }

    @Test fun fullVector() {
        val t = SafeTx(to = "0xa83c336b20401af773b6219ba5027174338d1836", value = "123456789", data = "0xdeadbeef00",
            operation = 1, safeTxGas = "50000", baseGas = "21000", gasPrice = "7",
            gasToken = "0x79a02482a880bce3f13e09da970dc34db4cd24d1", refundReceiver = "0x" + "44".repeat(20), nonce = "42")
        assertEquals("0x321d09105a40b0d115e6f2b294208a0fac9eb117f88c3d7ca5e036484aa591e1", SafeTx.hashHex(480, safe480, t))
        assertEquals("0xb0bcdc64af0c7fe223a8b673357104673dc659be0b9c98a9970d932a3c8cb2ac", SafeTx.hashHex(4801, safe480, t))
        val ctx = SafeTx.context(480, safe480, t)
        assertEquals(SafeTx.hashHex(480, safe480, t), SafeTx.expectCtxHash(ctx))
    }

    @Test fun amounts() {
        assertEquals("1500000000000000", SafeTx.ethToWei("0.0015"))
        assertEquals("1000000000000000000", SafeTx.ethToWei("1"))
        assertEquals("0", SafeTx.ethToWei("0.0"))
        assertNull(SafeTx.ethToWei("1e3"))
        assertEquals("42", SafeTx.hexToDec("0x2a"))
        assertEquals("0", SafeTx.hexToDec("0x0"))
    }
}
