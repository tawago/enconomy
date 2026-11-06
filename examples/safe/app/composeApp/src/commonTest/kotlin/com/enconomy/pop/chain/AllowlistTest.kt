package com.enconomy.pop.chain

import kotlin.test.Test
import kotlin.test.assertEquals

/** Same refusals as the backend's allowlist in examples/safe/backend/safe_tx.py. */
class AllowlistTest {
    private val chain = SafeTx.CHAIN_SEPOLIA
    private val safe = "0x" + "5a".repeat(20)
    private val to = "0x" + "11".repeat(20)
    private val usdc = "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238"
    private val pay = "0x" + "22".repeat(20)

    private fun reason(t: SafeTx) = (Allowlist.check(chain, safe, t) as Allowlist.Result.Refused).reason

    @Test fun native() {
        assertEquals(Allowlist.Result.Ok(Allowlist.What.Native(to, "1000")), Allowlist.check(chain, safe, SafeTx(to = to, value = "1000")))
    }

    @Test fun tokenShowsTokenAmountRecipient() {
        val t = SafeTx(to = usdc, data = SafeTx.transferData(pay, "1500000"))
        val what = (Allowlist.check(chain, safe, t) as Allowlist.Result.Ok).what as Allowlist.What.Erc20
        assertEquals("USDC", what.token.symbol)
        assertEquals(pay, what.to)
        assertEquals("1500000", what.amount)
    }

    @Test fun refusalsInOrder() {
        assertEquals("delegatecall", reason(SafeTx(to = to, value = "1", operation = 1, safeTxGas = "1")))
        assertEquals("gas_refund_fields", reason(SafeTx(to = to, value = "1", safeTxGas = "1")))
        assertEquals("gas_refund_fields", reason(SafeTx(to = to, value = "1", refundReceiver = pay)))
        assertEquals("self_call", reason(SafeTx(to = safe, value = "1")))
        assertEquals("value_with_call", reason(SafeTx(to = usdc, value = "1", data = SafeTx.transferData(pay, "1"))))
    }

    @Test fun unknownCalls() {
        val u = "unknown_call"
        assertEquals(u, reason(SafeTx(to = to)))                                                       // no value, no data
        assertEquals(u, reason(SafeTx(to = to, data = SafeTx.transferData(pay, "1"))))                 // not a listed token
        assertEquals(u, reason(SafeTx(to = usdc, data = SafeTx.transferData(pay, "0"))))               // zero amount
        // token approve reads as 0 ETH: it must not pass
        assertEquals(u, reason(SafeTx(to = usdc, data = "0x095ea7b3" + SafeTx.transferData(pay, "1").drop(10))))
        // dirty padding in the address word
        assertEquals(u, reason(SafeTx(to = usdc, data = "0xa9059cbb" + "01" + "00".repeat(11) + pay.drop(2) + "00".repeat(31) + "01")))
    }
}
