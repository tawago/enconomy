package com.enconomy.pop

/**
 * Invite codec, §3.2. 49 bytes:
 *
 *  0  4  magic "POP1"
 *  4  1  version 0x01
 *  5 16  session_id
 * 21 16  join_token
 * 37  4  expires_at, unix s, u32 BE
 * 41  8  sha256(host pubkey65)[:8]
 *
 * QR: "pop1:" + base64url(no pad). NFC: HCE answers SELECT(AID) with bytes ‖ 90 00.
 */
class Invite(
    val sessionId: String,
    val joinToken: String,
    val expiresAtS: Long,
    val hostHint: ByteArray,
) {
    init {
        require(sessionId.length == 32 && isHex(sessionId)) { "session_id: hex32" }
        require(joinToken.length == 32 && isHex(joinToken)) { "join_token: hex32" }
        require(expiresAtS in 0..0xffffffffL) { "expires_at: u32" }
        require(hostHint.size == 8) { "host hint: 8 bytes" }
    }

    fun encode(): ByteArray {
        val out = ByteArray(SIZE)
        MAGIC.copyInto(out, 0)
        out[4] = VERSION
        sessionId.hexToBytes().copyInto(out, 5)
        joinToken.hexToBytes().copyInto(out, 21)
        for (i in 0 until 4) out[37 + i] = (expiresAtS ushr (24 - 8 * i)).toByte()
        hostHint.copyInto(out, 41)
        return out
    }

    fun toQr(): String = QR_PREFIX + encode().toB64Url()

    fun expired(nowMs: Long): Boolean = nowMs / 1000 >= expiresAtS

    /** §3.3 step 2: partner pubkey (hex65) must hash to the hint. */
    fun matchesHost(pubkeyHex: String): Boolean =
        runCatching { keyHint(pubkeyHex.hexToBytes()).contentEquals(hostHint) }.getOrDefault(false)

    override fun equals(other: Any?): Boolean = other is Invite && encode().contentEquals(other.encode())
    override fun hashCode(): Int = encode().contentHashCode()
    override fun toString(): String = "Invite(${sessionId.take(8)}…, exp $expiresAtS)"

    companion object {
        const val SIZE = 49
        const val VERSION: Byte = 1
        const val QR_PREFIX = "pop1:"
        val MAGIC = "POP1".encodeToByteArray()

        fun keyHint(pubkey65: ByteArray): ByteArray = sha256(pubkey65).copyOf(8)

        fun decode(b: ByteArray): Invite {
            if (b.size != SIZE) throw InviteException("bad_length", "invite is ${b.size} bytes, want $SIZE")
            if (!b.copyOf(4).contentEquals(MAGIC)) throw InviteException("bad_magic", "not a POP1 invite")
            if (b[4] != VERSION) throw InviteException("bad_version", "invite version ${b[4]}")
            var exp = 0L
            for (i in 0 until 4) exp = (exp shl 8) or (b[37 + i].toLong() and 0xff)
            return Invite(
                sessionId = b.copyOfRange(5, 21).toHex(),
                joinToken = b.copyOfRange(21, 37).toHex(),
                expiresAtS = exp,
                hostHint = b.copyOfRange(41, 49),
            )
        }

        /** QR text: "pop1:<b64url>" (prefix case-insensitive, whitespace trimmed). */
        fun parse(text: String): Invite {
            val t = text.trim()
            if (!t.startsWith(QR_PREFIX, ignoreCase = true)) throw InviteException("bad_prefix", "not a pop1: code")
            val body = t.substring(QR_PREFIX.length)
            val bytes = try {
                body.fromB64Url()
            } catch (e: IllegalArgumentException) {
                throw InviteException("bad_base64", e.message ?: "bad base64url")
            }
            return decode(bytes)
        }

        /** Parse + reject expired. */
        fun parseValid(text: String, nowMs: Long): Invite = parse(text).also { it.checkFresh(nowMs) }
        fun decodeValid(b: ByteArray, nowMs: Long): Invite = decode(b).also { it.checkFresh(nowMs) }

        private fun Invite.checkFresh(nowMs: Long) {
            if (expired(nowMs)) throw InviteException("token_expired", "invite expired")
        }

        private fun isHex(s: String) = s.all { it in '0'..'9' || it in 'a'..'f' }
    }
}

class InviteException(val code: String, message: String) : Exception(message)

/** §3.2 HCE APDUs. AID F0 "ENCOPOP". */
object PopApdu {
    val AID: ByteArray = "F0454E434F504F50".hexToBytes()
    val SELECT: ByteArray = byteArrayOf(0x00, 0xA4.toByte(), 0x04, 0x00, AID.size.toByte()) + AID + byteArrayOf(0x00)
    val SW_OK = byteArrayOf(0x90.toByte(), 0x00)
    val SW_NOT_FOUND = byteArrayOf(0x6A, 0x82.toByte())

    /** SELECT by name of our AID (Le optional). */
    fun isSelect(apdu: ByteArray): Boolean {
        if (apdu.size < 5 + AID.size) return false
        if (apdu[0] != 0x00.toByte() || apdu[1] != 0xA4.toByte() || apdu[2] != 0x04.toByte()) return false
        if (apdu[4].toInt() != AID.size) return false
        return apdu.copyOfRange(5, 5 + AID.size).contentEquals(AID)
    }

    /** Card side. [invite] = current bytes, or null when the host is not on the invite screen. */
    fun respond(apdu: ByteArray, invite: ByteArray?): ByteArray =
        if (isSelect(apdu) && invite != null && invite.size == Invite.SIZE) invite + SW_OK else SW_NOT_FOUND

    /** Reader side. */
    fun parseResponse(resp: ByteArray): ByteArray {
        if (resp.size < 2) throw InviteException("nfc_bad_response", "short APDU response")
        val sw = resp.copyOfRange(resp.size - 2, resp.size)
        if (sw.contentEquals(SW_NOT_FOUND)) throw InviteException("nfc_no_invite", "host has no invite ready")
        if (!sw.contentEquals(SW_OK)) throw InviteException("nfc_bad_response", "SW ${sw.toHex()}")
        return resp.copyOfRange(0, resp.size - 2)
    }
}
