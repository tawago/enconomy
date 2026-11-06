package com.enconomy.pop.zk

import com.enconomy.pop.derToRawRs
import com.enconomy.pop.ecdsaP256Verify
import com.enconomy.pop.hexToBytes
import com.enconomy.pop.rawRsToDer
import com.enconomy.pop.toB64
import com.enconomy.pop.toHex
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Holder commit + SBcred3 against optionA-v2 fixtures/popt_v2/b550cf12_48k.json (dev issuer). */
class HolderTest {
    private val issuer = ("04" + "9178141b72e5cae00db063dbd38fda4f82a11e1dc8442d2735604719630d99b6" +
        "4b75c24fb3128f0646642e3828848d23348f1e08023f5378425a28cffd1885e3").hexToBytes()

    private class Role(val pub: String, val secret: String, val commit: String, val cred: String, val r: String, val s: String)

    private val a = Role(
        pub = "04a3add80f0b308b87f91990aad20b1ba09eac2329cc4ca80940a29c5b27becd0c5c70ca6cb12805dde021f95dab3e2a0292c8642d98cdecdf65f7fb6d39690f43",
        secret = "2a58855e7f343e13ae2bd5d3562bf733580bc2518c8e182ea47422dcee57f0",
        commit = "aaaeca29076eb4906155efaed4021462b075b85eebd9d4f1b66d840e200d654c",
        cred = "53426372656433a3add80f0b308b87f91990aad20b1ba09eac2329cc4ca80940a29c5b27becd0c5c70ca6cb12805dde021f95dab3e2a0292c8642d98cdecdf65f7fb6d39690f43000000006ade3469aaaeca29076eb4906155efaed4021462b075b85eebd9d4f1b66d840e200d654c",
        r = "9b7c867f13429796717f77c83e5541c4b3527a594612069c1b3c2ebd98f3f3d3",
        s = "32d06f3c1829c704382ee1237734f2c96307f284ca20f998481d7e1c235d57bf",
    )
    private val b = Role(
        pub = "04f567fcdaa2cb002d7b91763b5314008716328fb8d943c0a6f592badceae25b5901c7d236f785b1092a640d86e5bea0e96fb9366ba30781351fdc7b0f200b1c1c",
        secret = "9bfa2e3e0e3190e01555c62251f84e1f156b7b096793a0b97f980ee8d457b0",
        commit = "66ae655b7d532a667dd4e878f46a7079a3e4162479a59f8b99f4be6d4b271c48",
        cred = "53426372656433f567fcdaa2cb002d7b91763b5314008716328fb8d943c0a6f592badceae25b5901c7d236f785b1092a640d86e5bea0e96fb9366ba30781351fdc7b0f200b1c1c000000006ade346966ae655b7d532a667dd4e878f46a7079a3e4162479a59f8b99f4be6d4b271c48",
        r = "94dac6c75f8cc14d21521e2791c4bc391e3dd412f4ef029c5364af0fb2dd2a23",
        s = "3bee2bc8d4d9def58888ae0ea6bc72125cf8bf8afec9aa7cd0df51c5f4c4c534",
    )
    private val expiry = 1792947305L

    @Test fun commitSpotValue() {
        // spec §1.2: sponge16(6, [1])
        val one = ByteArray(31).also { it[30] = 1 }
        assertEquals("892b94c43e27b362a254ccbfe2480510cc7a2930e0dc8ea82d69f4b8e1e94714", Holder.commit(one).toHex())
    }

    @Test fun commitFixtures() {
        for (r in listOf(a, b)) assertEquals(r.commit, Holder.commit(r.secret.hexToBytes()).toHex())
    }

    @Test fun secretLength() {
        assertFailsWith<IllegalArgumentException> { Holder.commit(ByteArray(32)) }
        assertFailsWith<IllegalArgumentException> { Holder.commit(ByteArray(30)) }
        // max 31 bytes is < 2^248 < p
        assertEquals(64, Holder.commit(ByteArray(31) { -1 }).toHex().length)
    }

    @Test fun credLayout() {
        for (r in listOf(a, b)) {
            val c = Sbcred3.build(r.pub.hexToBytes(), expiry, r.commit.hexToBytes())
            assertEquals(r.cred, c.bytes.toHex())
            assertEquals(111, c.bytes.size)
            val p = Sbcred3(r.cred.hexToBytes())
            assertEquals(expiry, p.expiry)
            assertContentEquals(r.pub.hexToBytes().copyOfRange(1, 65), p.devicePub64)
            assertEquals(r.commit, p.holderCommit.toHex())
        }
        assertFailsWith<IllegalArgumentException> { Sbcred3(ByteArray(111)) }
        assertFailsWith<IllegalArgumentException> { Sbcred3(a.cred.hexToBytes().copyOf(110)) }
    }

    @Test fun issuerSignature() {
        for (r in listOf(a, b)) {
            val sig = (r.r + r.s).hexToBytes()
            val cred = r.cred.hexToBytes()
            assertTrue(ecdsaP256Verify(issuer, cred, sig))
            assertFalse(ecdsaP256Verify(issuer, cred.copyOf().also { it[80] = (it[80] + 1).toByte() }, sig))
            assertFalse(ecdsaP256Verify(r.pub.hexToBytes(), cred, sig))
            assertFalse(ecdsaP256Verify(issuer, cred, ByteArray(64)))
            assertFalse(ecdsaP256Verify(issuer.copyOf(64), cred, sig))
        }
    }

    @Test fun derRoundTrip() {
        for (r in listOf(a, b)) {
            val raw = (r.r + r.s).hexToBytes()
            assertContentEquals(raw, derToRawRs(rawRsToDer(raw)))
        }
        // high bit gets a 0x00 pad, leading zeros are stripped
        val raw = ByteArray(64).also { it[0] = 0x80.toByte(); it[33] = 0x05 }
        val der = rawRsToDer(raw)
        assertEquals(0x21, der[3].toInt())
        assertContentEquals(raw, derToRawRs(der))
    }

    private fun accept(
        r: Role = a,
        pinned: ByteArray = issuer,
        claimed: String? = issuer.toHex(),
        commit: String = r.commit,
        pub: String = r.pub,
        exp: Long = expiry,
        format: String = "SBcred3",
        sig: String = r.r + r.s,
    ) = acceptCredential(format, r.cred.hexToBytes().toB64(), sig.hexToBytes().toB64(), exp, claimed, pinned, pub.hexToBytes(), commit.hexToBytes())

    @Test fun acceptChecks() {
        assertEquals(expiry, accept().expiry)
        assertEquals(expiry, accept(r = b, claimed = null).expiry)
        fun reason(block: () -> Unit) = assertFailsWith<CredentialException> { block() }.reason
        assertEquals("bad_format", reason { accept(format = "SBcred2") })
        assertEquals("wrong_key", reason { accept(pub = b.pub) })
        assertEquals("wrong_commit", reason { accept(commit = b.commit) })
        assertEquals("bad_expiry", reason { accept(exp = expiry + 1) })
        assertEquals("issuer_unknown", reason { accept(claimed = a.pub) })
        assertEquals("issuer_unknown", reason { accept(pinned = a.pub.hexToBytes(), claimed = null) })
        assertEquals("issuer_unknown", reason { accept(sig = b.r + b.s) })
        assertEquals("bad_sig", reason { accept(sig = a.r) })
    }
}
