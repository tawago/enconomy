package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class InviteCodecTest {
    // vector from server/pop/invite.py (pubkey = 04 01..40)
    private val pk = (byteArrayOf(4) + ByteArray(64) { (it + 1).toByte() }).toHex()
    private val hex = "504f50310100112233445566778899aabbccddeeffffeeddccbbaa998877665544332211006ab13b800ed3a6ab957ff6f5"
    private val qr = "pop1:UE9QMQEAESIzRFVmd4iZqrvM3e7__-7dzLuqmYh3ZlVEMyIRAGqxO4AO06arlX_29Q"
    private val inv = Invite(
        "00112233445566778899aabbccddeeff", "ffeeddccbbaa99887766554433221100", 1790000000L,
        Invite.keyHint(pk.hexToBytes()),
    )

    @Test fun serverVector() {
        assertEquals("0ed3a6ab957ff6f5", inv.hostHint.toHex())
        assertEquals(hex, inv.encode().toHex())
        assertEquals(49, inv.encode().size)
        assertEquals(qr, inv.toQr())
        assertEquals(inv, Invite.parse(qr))
        assertEquals(inv, Invite.decode(hex.hexToBytes()))
    }

    @Test fun roundTripHighExpiry() {
        val i = Invite("ab".repeat(16), "cd".repeat(16), 0xfffffffeL, ByteArray(8) { -1 })
        val d = Invite.decode(i.encode())
        assertEquals(0xfffffffeL, d.expiresAtS)
        assertEquals(i, d)
        assertEquals(i, Invite.parse("  POP1:" + i.encode().toB64Url() + "\n"))
    }

    @Test fun rejects() {
        val b = hex.hexToBytes()
        assertEquals("bad_length", assertFailsWith<InviteException> { Invite.decode(b.copyOf(48)) }.code)
        assertEquals("bad_magic", assertFailsWith<InviteException> { Invite.decode(b.copyOf().also { it[0] = 0 }) }.code)
        assertEquals("bad_version", assertFailsWith<InviteException> { Invite.decode(b.copyOf().also { it[4] = 2 }) }.code)
        assertEquals("bad_prefix", assertFailsWith<InviteException> { Invite.parse("https://x/" + qr) }.code)
        assertEquals("bad_base64", assertFailsWith<InviteException> { Invite.parse("pop1:!!!") }.code)
        assertFailsWith<IllegalArgumentException> { Invite("xyz", "cd".repeat(16), 1, ByteArray(8)) }
    }

    @Test fun expiry() {
        assertFalse(inv.expired(1789999999_999))
        assertTrue(inv.expired(1790000000_000))
        Invite.parseValid(qr, 1789999000_000)
        assertEquals("token_expired", assertFailsWith<InviteException> { Invite.parseValid(qr, 1790000001_000) }.code)
        assertEquals("token_expired", assertFailsWith<InviteException> { Invite.decodeValid(hex.hexToBytes(), 1790000001_000) }.code)
    }

    @Test fun hostHint() {
        assertTrue(inv.matchesHost(pk))
        assertFalse(inv.matchesHost("04" + "00".repeat(64)))
        assertFalse(inv.matchesHost("zz"))
    }

    @Test fun apdu() {
        assertEquals("00a4040008f0454e434f504f5000", PopApdu.SELECT.toHex())
        assertTrue(PopApdu.isSelect(PopApdu.SELECT))
        assertTrue(PopApdu.isSelect(PopApdu.SELECT.copyOf(13))) // no Le
        assertFalse(PopApdu.isSelect("00a4040007a0000002471001".hexToBytes()))
        val b = inv.encode()
        val ok = PopApdu.respond(PopApdu.SELECT, b)
        assertEquals(51, ok.size)
        assertEquals("9000", ok.copyOfRange(49, 51).toHex())
        assertContentEquals(b, PopApdu.parseResponse(ok))
        assertEquals(inv, Invite.decode(PopApdu.parseResponse(ok)))
        assertEquals("6a82", PopApdu.respond(PopApdu.SELECT, null).toHex())
        assertEquals("6a82", PopApdu.respond("00b0000000".hexToBytes(), b).toHex())
        assertEquals("nfc_no_invite", assertFailsWith<InviteException> { PopApdu.parseResponse(PopApdu.SW_NOT_FOUND) }.code)
        assertEquals("nfc_bad_response", assertFailsWith<InviteException> { PopApdu.parseResponse("6f00".hexToBytes()) }.code)
    }
}
