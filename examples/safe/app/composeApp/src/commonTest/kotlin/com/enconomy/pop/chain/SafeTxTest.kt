package com.enconomy.pop.chain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** examples/safe/tests/test_safe_tx.py ROW vectors. */
class SafeTxTest {
    private val safe480 = "0x3fad7600f309b0c3d60a57023b0262460b0603dc"
    private val wld = "0x2cfc85d8e48f8eab294be644d9e25c3030863003"

    @Test fun nativeVector() {
        val t = SafeTx(to = "0x" + "11".repeat(20), value = "10000000000000000")
        assertEquals("0x960376ecf47efc7cff7bfae13f9f9f1f678c1429cb6489486a3ef315df1f59a5", SafeTx.hashHex(480, safe480, t))
    }

    @Test fun tokenVector() {
        val t = SafeTx(to = wld, data = SafeTx.transferData("0x" + "22".repeat(20), "1500000000000000000"))
        assertEquals("0x320418179acf57e8607ddcb3f82e113cb45d0d7579b95ccb81ee04afc056a3ce", SafeTx.hashHex(480, safe480, t))
    }

    @Test fun fullVector() {
        val t = SafeTx(to = "0xa83c336b20401af773b6219ba5027174338d1836", value = "123456789", data = "0xdeadbeef00",
            operation = 1, safeTxGas = "50000", baseGas = "21000", gasPrice = "7",
            gasToken = "0x79a02482a880bce3f13e09da970dc34db4cd24d1", refundReceiver = "0x" + "44".repeat(20), nonce = "42")
        assertEquals("0x321d09105a40b0d115e6f2b294208a0fac9eb117f88c3d7ca5e036484aa591e1", SafeTx.hashHex(480, safe480, t))
        assertEquals("0xb0bcdc64af0c7fe223a8b673357104673dc659be0b9c98a9970d932a3c8cb2ac", SafeTx.hashHex(4801, safe480, t))
        assertEquals(setOf("chain_id", "consumer", "ctx_hash"), SafeTx.context(480, safe480, t).keys)
        assertEquals(t, SafeTx.fromJson(t.json()))
    }

    @Test fun amounts() {
        assertEquals("1500000000000000", SafeTx.toUnits("0.0015", 18))
        assertEquals("1000000000000000000", SafeTx.toUnits("1", 18))
        assertEquals("1500000", SafeTx.toUnits("1.5", 6))
        assertEquals("0", SafeTx.toUnits("0.0", 18))
        assertNull(SafeTx.toUnits("1e3", 18))
        assertNull(SafeTx.toUnits("0.0000001", 6))
        assertEquals("1.5", SafeTx.formatUnits("1500000", 6))
        assertEquals("0.001", SafeTx.formatUnits("1000000000000000", 18))
        assertEquals("42", SafeTx.hexToDec("0x2a"))
        assertEquals("0", SafeTx.hexToDec("0x0"))
    }
}
