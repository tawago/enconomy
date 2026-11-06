import com.enconomy.pop.FrameKey
import com.enconomy.pop.FrameSig
import com.enconomy.pop.derToRawRs
import org.kotlincrypto.hash.sha3.Keccak256
import java.io.File
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * JVM stand-in for AndroidFrameKey: SunEC "NONEwithECDSA" = ECDSA over the input bytes as e,
 * the same contract AndroidKeyStore gives for a DIGEST_NONE key. Same post-processing as the phone:
 * DER -> r||s (app's derToRawRs) -> FrameSig.normalizeLowS.
 */
class JvmFrameKey : FrameKey {
    private val kp = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    override val pubkey: ByteArray = (kp.public as ECPublicKey).w.let { byteArrayOf(4) + f32(it.affineX) + f32(it.affineY) }
    override val securityLevel = "software"
    /** DER straight from the provider, before any normalization. */
    fun signDer(d: ByteArray, alg: String = "NONEwithECDSA"): ByteArray =
        Signature.getInstance(alg).apply { initSign(kp.private); update(d) }.sign()
    override fun signDigest(digest32: ByteArray): ByteArray {
        FrameSig.requireDigest(digest32)
        return FrameSig.normalizeLowS(derToRawRs(signDer(digest32)))
    }
    fun javaVerifyRaw(d: ByteArray, rs: ByteArray): Boolean =
        Signature.getInstance("NONEwithECDSA").apply { initVerify(kp.public); update(d) }.verify(rawToDer(rs))
}

fun f32(v: BigInteger): ByteArray = v.toByteArray().let { if (it.size >= 32) it.copyOfRange(it.size - 32, it.size) else ByteArray(32 - it.size) + it }
fun b32(v: BigInteger) = f32(v)
fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
fun unhex(h: String) = ByteArray(h.length / 2) { h.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

fun rawToDer(rs: ByteArray): ByteArray {
    fun int(b: ByteArray): ByteArray {
        var v = b.dropWhile { it == 0.toByte() }.toByteArray()
        if (v.isEmpty()) v = byteArrayOf(0)
        if (v[0] < 0) v = byteArrayOf(0) + v
        return byteArrayOf(2, v.size.toByte()) + v
    }
    val body = int(rs.copyOfRange(0, 32)) + int(rs.copyOfRange(32, 64))
    return byteArrayOf(0x30, body.size.toByte()) + body
}

class FrameSigTest {
    private val rnd = SecureRandom()
    private val n = Scheme2.N
    private val halfN = n.shiftRight(1)
    private fun digest() = ByteArray(32).also { rnd.nextBytes(it) }
    private val vectorsDir = File(System.getProperty("vectors.dir") ?: "../vectors")

    @Test fun constants() {
        assertContentEquals(b32(n), FrameSig.N)
        assertContentEquals(b32(halfN), FrameSig.HALF_N)
        // keccak256("") sanity, so "keccak" really is Keccak-256 and not SHA3-256
        assertEquals("c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", hex(Keccak256().digest(ByteArray(0))))
    }

    @Test fun lowSEdges() {
        val r = b32(BigInteger.ONE)
        fun norm(s: BigInteger) = BigInteger(1, FrameSig.normalizeLowS(r + b32(s)).copyOfRange(32, 64))
        assertEquals(halfN, norm(halfN), "n/2 is already low")
        assertEquals(halfN, norm(halfN + BigInteger.ONE), "n/2+1 -> n-(n/2+1) = n/2 (n odd)")
        assertEquals(BigInteger.ONE, norm(BigInteger.ONE))
        assertEquals(BigInteger.ONE, norm(n - BigInteger.ONE))
        assertFailsWith<IllegalArgumentException> { FrameSig.normalizeLowS(r + b32(BigInteger.ZERO)) }
        assertFailsWith<IllegalArgumentException> { FrameSig.normalizeLowS(r + b32(n)) }
    }

    @Test fun lowSRandomMatchesBigInteger() {
        repeat(10_000) {
            val s = BigInteger(256, rnd).mod(n - BigInteger.ONE) + BigInteger.ONE
            val rs = b32(BigInteger.TEN) + b32(s)
            val out = FrameSig.normalizeLowS(rs)
            val want = if (s > halfN) n - s else s
            assertEquals(want, BigInteger(1, out.copyOfRange(32, 64)))
            assertContentEquals(out, FrameSig.normalizeLowS(out), "idempotent")
            assertContentEquals(rs.copyOfRange(0, 32), out.copyOfRange(0, 32), "r untouched")
        }
    }

    /** The core claim: digest-mode signature + low-s passes every scheme-2 rule against the RAW digest. */
    @Test fun digestModePassesScheme2() {
        val key = JvmFrameKey()
        val signer = FrameSig.signer(key.pubkey)
        var high = 0
        val vectors = mutableListOf<String>()
        repeat(256) { i ->
            val d = digest()
            val raw = derToRawRs(key.signDer(d))
            val s = BigInteger(1, raw.copyOfRange(32, 64))
            val wasHigh = s > halfN
            if (wasHigh) {
                high++
                // un-normalized high-s: valid ECDSA, rejected by scheme 2
                assertTrue(Scheme2.p256verify(d, BigInteger(1, raw.copyOfRange(0, 32)), s, BigInteger(1, key.pubkey.copyOfRange(1, 33)), BigInteger(1, key.pubkey.copyOfRange(33, 65))))
                assertEquals(Scheme2.Result.S_RANGE_OR_HIGH, Scheme2.validate(d, ByteArray(32), signer, raw + FrameSig.qxqy(key.pubkey)))
                assertFailsWith<IllegalArgumentException> { FrameSig.scheme2Bytes(raw, key.pubkey) }
            }
            val low = FrameSig.normalizeLowS(raw)
            val entry = FrameSig.scheme2Bytes(low, key.pubkey)
            // as explicit msg (signatures[1], partner over D)
            assertEquals(Scheme2.Result.OK, Scheme2.validate(d, ByteArray(32), signer, entry))
            // as empty msg (signatures[0], over sig_hash)
            assertEquals(Scheme2.Result.OK, Scheme2.validate(ByteArray(0), d, signer, entry))
            // the provider's own verifier agrees after normalization
            assertTrue(key.javaVerifyRaw(d, low))
            if (i < 8) vectors += vec("jvm-sunec", key.pubkey, d, raw, low, wasHigh)
        }
        println("digestModePassesScheme2: 256 sigs, $high came out high-s and were normalized")
        assertTrue(high in 64..192, "expected roughly half high-s, got $high")
        // signDigest() is the API the app calls
        val d = digest()
        assertEquals(Scheme2.Result.OK, Scheme2.validate(d, ByteArray(32), signer, FrameSig.scheme2Bytes(key.signDigest(d), key.pubkey)))
        writeVectors("jvm-vectors.json", vectors)
    }

    /** What the app does today (message mode) fails against the raw digest: the trap from notes §6a. */
    @Test fun messageModeFails() {
        val key = JvmFrameKey()
        val signer = FrameSig.signer(key.pubkey)
        val d = digest()
        val low = FrameSig.normalizeLowS(derToRawRs(key.signDer(d, "SHA256withECDSA")))
        val entry = FrameSig.scheme2Bytes(low, key.pubkey)
        assertEquals(Scheme2.Result.P256VERIFY_FAIL, Scheme2.validate(d, ByteArray(32), signer, entry))
        val sha = MessageDigest.getInstance("SHA-256").digest(d)
        assertEquals(Scheme2.Result.OK, Scheme2.validate(sha, ByteArray(32), signer, entry), "it signed sha256(d)")
    }

    @Test fun otherRules() {
        val key = JvmFrameKey()
        val d = digest()
        val entry = FrameSig.scheme2Bytes(key.signDigest(d), key.pubkey)
        val signer = FrameSig.signer(key.pubkey)
        assertEquals(Scheme2.Result.SIGNER_MISMATCH, Scheme2.validate(d, ByteArray(32), ByteArray(20), entry))
        // signer must be the LAST 20 bytes of keccak(qx||qy)
        val first20 = Keccak256().digest(FrameSig.qxqy(key.pubkey)).copyOfRange(0, 20)
        assertEquals(Scheme2.Result.SIGNER_MISMATCH, Scheme2.validate(d, ByteArray(32), first20, entry))
        assertEquals(Scheme2.Result.BAD_MSG, Scheme2.validate(ByteArray(32), ByteArray(32), signer, entry))
        assertEquals(Scheme2.Result.BAD_MSG, Scheme2.validate(ByteArray(31) { 1 }, ByteArray(32), signer, entry))
        assertEquals(Scheme2.Result.BAD_LEN, Scheme2.validate(d, ByteArray(32), signer, entry.copyOf(127)))
        val other = digest()
        assertEquals(Scheme2.Result.P256VERIFY_FAIL, Scheme2.validate(other, ByteArray(32), signer, entry))
        assertFailsWith<IllegalArgumentException> { key.signDigest(ByteArray(33)) }
        assertFailsWith<IllegalArgumentException> { key.signDigest(ByteArray(32)) }
    }

    /**
     * Signatures made by macOS Security.framework (ios/sign_digest.swift): the exact call the iOS app
     * would make, kSecKeyAlgorithmECDSASignatureDigestX962SHA256 over 32 bytes, software key and
     * (on this M2) a Secure Enclave key. Skipped if the file isn't there.
     */
    @Test fun appleDigestVectorsPassScheme2() {
        val f = File(vectorsDir, "macos-seckey.json")
        if (!f.exists()) { println("SKIP: ${f.path} missing"); return }
        @Suppress("UNCHECKED_CAST")
        val root = MiniJson(f.readText()).parse() as Map<String, Any?>
        val out = mutableListOf<String>()
        @Suppress("UNCHECKED_CAST")
        for (k in root["keys"] as List<Map<String, Any?>>) {
            val label = k["key"] as String
            val pub = unhex(k["pub"] as String)
            val signer = FrameSig.signer(pub)
            var high = 0; var count = 0
            @Suppress("UNCHECKED_CAST")
            for ((i, v) in (k["vectors"] as List<Map<String, String>>).withIndex()) {
                val d = unhex(v.getValue("digest"))
                val raw = derToRawRs(unhex(v.getValue("der")))
                val wasHigh = !FrameSig.isLowS(raw.copyOfRange(32, 64))
                if (wasHigh) high++
                val low = FrameSig.normalizeLowS(raw)
                assertEquals(Scheme2.Result.OK, Scheme2.validate(d, ByteArray(32), signer, FrameSig.scheme2Bytes(low, pub)), "$label #$i")
                val mm = v["derMessageMode"].orEmpty()
                if (mm.isNotEmpty()) {
                    val mlow = FrameSig.normalizeLowS(derToRawRs(unhex(mm)))
                    assertEquals(Scheme2.Result.P256VERIFY_FAIL, Scheme2.validate(d, ByteArray(32), signer, FrameSig.scheme2Bytes(mlow, pub)), "$label msg-mode #$i")
                }
                if (i < 8) out += vec("macos-$label", pub, d, raw, low, wasHigh)
                count++
            }
            println("apple $label: $count digest-mode sigs pass scheme 2 after low-s ($high were high-s); message-mode all fail")
            assertTrue(count > 0)
        }
        writeVectors("apple-vectors.json", out)
    }

    private fun vec(src: String, pub: ByteArray, d: ByteArray, raw: ByteArray, low: ByteArray, high: Boolean) =
        """{"src":"$src","pub":"${hex(pub)}","digest":"${hex(d)}","rsRaw":"${hex(raw)}","rsLow":"${hex(low)}","wasHighS":$high,"signer":"${FrameSig.signerHex(pub)}","scheme2":"${hex(FrameSig.scheme2Bytes(low, pub))}"}"""

    private fun writeVectors(name: String, v: List<String>) {
        vectorsDir.mkdirs()
        File(vectorsDir, name).writeText("[\n" + v.joinToString(",\n") + "\n]\n")
    }
}

/** Enough JSON for the Swift output (objects, arrays, strings, bools, numbers). */
class MiniJson(private val s: String) {
    private var i = 0
    fun parse(): Any? { ws(); return value() }
    private fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
    private fun value(): Any? {
        ws()
        return when (s[i]) {
            '{' -> { i++; val m = LinkedHashMap<String, Any?>(); ws(); if (s[i] == '}') { i++; return m }
                while (true) { ws(); val k = str(); ws(); i++ /* : */; m[k] = value(); ws(); if (s[i++] == '}') break }; m }
            '[' -> { i++; val l = ArrayList<Any?>(); ws(); if (s[i] == ']') { i++; return l }
                while (true) { l += value(); ws(); if (s[i++] == ']') break }; l }
            '"' -> str()
            't' -> { i += 4; true }
            'f' -> { i += 5; false }
            'n' -> { i += 4; null }
            else -> { val st = i; while (i < s.length && (s[i].isDigit() || s[i] in "-+.eE")) i++; s.substring(st, i).toDouble() }
        }
    }
    private fun str(): String {
        i++ // "
        val b = StringBuilder()
        while (s[i] != '"') { if (s[i] == '\\') { i++; b.append(when (s[i]) { 'n' -> '\n'; 't' -> '\t'; else -> s[i] }) } else b.append(s[i]); i++ }
        i++
        return b.toString()
    }
}
