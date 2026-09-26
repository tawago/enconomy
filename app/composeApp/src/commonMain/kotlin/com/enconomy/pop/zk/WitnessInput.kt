package com.enconomy.pop.zk

import com.enconomy.pop.TranscriptCodec
import com.enconomy.pop.dsp.Popt2Code
import com.enconomy.pop.dsp.Popt2Rate
import com.enconomy.pop.dsp.Popt2Rates
import com.enconomy.pop.dsp.Popt2Rule
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.abs

/** What the phone holds after a POPT v2 attempt; enough to build the option A witness. */
class ProofSource(
    /** Signed POPT v2, 311 bytes. */
    val transcript: ByteArray,
    /** raw r||s over sha256(transcript). */
    val sig: ByteArray,
    val capture: ShortArray,
    val own: Popt2Code,
    val partner: Popt2Code,
    val cred: Sbcred3,
    /** issuer raw r||s over sha256(cred). */
    val credSig: ByteArray,
    /** 04||X||Y. */
    val issuerPub: ByteArray,
    /** Unix s the verifier pins; credential expiry must be ≥ it. */
    val validAt: Long,
    /** 31 random bytes (< 2^248), fresh per proof; opens halfCommit for the pair proof. */
    val salt: ByteArray,
    /** Tree built during the run (rebuilt from [capture] when null). */
    val tree: OaHash.RecTree2? = null,
)

class UnprovableException(val reason: String, msg: String) : Exception("$reason: $msg")

/**
 * Input map of the Noir option A circuit `noir/phone` (research/worldid/prototypes/optA-noir, gen_inputs.py
 * encodings): the ABI parameters of phone.json in order, JSON-encoded as noirc_abi reads it (Field = decimal
 * string, uN = number, bool = true/false). The same map is fed to the phone's ACVM (zkprove) or sent to the
 * server for a delegated proof (zkmobile/APP_SERVER_CONTRACT.md).
 * Transcript fields are the signed bytes themselves. Before building, the circuit's conditions are re-checked
 * here (integer rule at a_self and a_partner, |self_os_delta| ≤ delta, geometry, code_commit, rec_root,
 * credential), so a doomed proof is refused in milliseconds instead of after the native witness.
 */
object WitnessInput {
    const val CIRCUIT_S48 = "oaN_s48"
    /** Public inputs of the proof: 11 ABI publics + the returned halfCommit, 32 B each. */
    const val N_PUBLIC = 12

    class Built(
        val circuit: String,
        val sampleRate: Int,
        val fields: JsonObject,
        /** halfCommit = the circuit's return value, public input #12. */
        val halfCommit: Fr,
        /** The 12 public inputs an honest verifier derives, 32-byte BE each (bb public_inputs layout). */
        val expectedPublic: ByteArray,
        val salt: ByteArray,
    ) {
        val json: String by lazy { fields.toString() }
    }

    fun circuitFor(sr: Int): String? = if (sr == 48000) CIRCUIT_S48 else null

    /** ECDSA P-256 raw r||s -> low-S (s > n/2 -> n - s); bb's secp256r1 blackbox rejects high-S. */
    fun lowS(sig: ByteArray): ByteArray {
        require(sig.size == 64)
        val s = BigNat.fromBytes(sig.copyOfRange(32, 64))
        if (s <= HALF_N) return sig
        return sig.copyOfRange(0, 32) + (BigNat.N - s).toBytes(32)
    }

    private val HALF_N: BigNat by lazy { BigNat.fromHex("7FFFFFFF800000007FFFFFFFFFFFFFFFDE737D56D38BCF4279DCE5617E3192A8") }

    fun build(s: ProofSource): Built {
        fun no(reason: String, msg: String): Nothing = throw UnprovableException(reason, msg)
        val raw = s.transcript
        val t = runCatching { TranscriptCodec.decodeTranscript2(raw) }.getOrElse { no("bad_transcript", it.message ?: "") }
        val circuit = circuitFor(t.sampleRate) ?: no("no_circuit", "no circuit for ${t.sampleRate} Hz (48 kHz only)")
        val rate = Popt2Rates.builtIn[t.sampleRate] ?: no("no_circuit", "no rate constants for ${t.sampleRate} Hz")
        val L = rate.L
        val hm = Popt2Rule.HM
        if (t.delta != rate.delta) no("bad_transcript", "delta ${t.delta} != ${rate.delta}")
        if (s.sig.size != 64 || s.credSig.size != 64) no("bad_sig", "signatures must be raw r||s")
        if (s.salt.size != 31) no("bad_salt", "salt must be 31 bytes")
        if (s.own.n != L || s.partner.n != L) no("bad_code", "code length != $L")
        if (raw[39] != 4.toByte() || raw[104] != 4.toByte()) no("bad_transcript", "pubkeys must be SEC1 uncompressed")
        if (raw.copyOfRange(40, 72).contentEquals(raw.copyOfRange(105, 137))) no("bad_transcript", "own X == partner X")
        if (!s.cred.devicePub64.contentEquals(raw.copyOfRange(40, 104))) no("wrong_credential", "credential is for another key")
        if (s.cred.expiry < s.validAt) no("credential_expired", "credential expiry ${s.cred.expiry} < validAt ${s.validAt}")
        if (s.issuerPub.size != 65 || s.issuerPub[0] != 4.toByte()) no("bad_issuer", "issuer pub must be 04||X||Y")
        val cc = CodeCommit.compute(s.own.cI, s.own.cQ, s.partner.cI, s.partner.cQ)
        if (!cc.contentEquals(t.codeCommit)) no("code_commit", "codes do not match the signed code_commit")
        val tree = s.tree ?: OaHash.recTree(s.capture)
        if (!tree.rootBytes().contentEquals(t.recRoot)) no("rec_root", "capture does not match the signed rec_root")

        // provability (port spec §3.7)
        val pSelf = t.pSelf
        val aSelf = t.aSelf
        val aPartner = t.aPartner
        val d = rate.delta
        if (abs(t.selfOsDelta) > d) no("self_os_delta", "|self_os_delta| ${abs(t.selfOsDelta)} > delta $d")
        val lo = pSelf - d
        if (lo - hm < 0 || aPartner - hm < 0) no("geometry", "window starts before the capture")
        if (aPartner !in (t.pPartner - rate.wpre)..(t.pPartner + rate.wpost)) no("geometry", "a_partner outside its window")
        val g = Geometry.of(rate)
        if (g.nls != NL || g.nlp != NL) no("geometry", "circuit opens $NL leaves, rate needs ${g.nls}/${g.nlp}")
        val leafS = (lo - hm) / OaHash.LEAF
        val leafP = (aPartner - hm) / OaHash.LEAF
        if (leafS + NL > OaHash.NLEAVES || leafP + NL > OaHash.NLEAVES) no("geometry", "window past the tree")
        if (aSelf - lo !in 0 until g.k) no("self_os_delta", "a_self $aSelf outside the self window from $lo (${g.k} samples)")

        val self = Curve.of(s.capture, s.own, lo, g.k, rate)
        val ja = aSelf - lo
        for (j in 0 until ja) if (self.pass(j)) no("self_rule", "own code passes at ${lo + j}, before a_self $aSelf")
        if (!self.pass(ja)) no("self_rule", "own code does not pass at a_self $aSelf")
        if (!Curve.of(s.capture, s.partner, aPartner, 1, rate).pass(0)) no("partner_rule", "partner code does not pass at a_partner $aPartner")

        val nonce = t.sessionNonce
        val nonceHi = Fr.fromBytesSmall(nonce, 0, 16)
        val nonceLo = Fr.fromBytesSmall(nonce, 16, 16)
        val roleB = t.role == 'B'
        val codeFr = Fr.fromBytesReduce(cc)
        val iss = listOf(1, 17, 33, 49).map { Fr.fromBytesSmall(s.issuerPub, it, 16) }
        val saltFr = Fr.fromBytesSmall(s.salt)

        fun dec(f: Fr) = JsonPrimitive(f.toDecimal())
        fun u8s(b: ByteArray) = JsonArray(List(b.size) { JsonPrimitive(b[it].toInt() and 0xff) })
        fun tpl(b: ByteArray) = JsonArray(List(b.size) { JsonPrimitive(b[it] + 128) })
        fun open(first: Int): Pair<JsonArray, JsonArray> {
            val base = first * OaHash.LEAF
            val xs = JsonArray(List(NL * OaHash.LEAF) { k ->
                val idx = base + k
                JsonPrimitive((if (idx < s.capture.size) s.capture[idx].toInt() else 0) + 32768)
            })
            val ch = JsonArray(List(NL) { i ->
                JsonArray(tree.path(first + i).map { lvl -> JsonArray(lvl.map { dec(it) }) })
            })
            return xs to ch
        }
        val (xs, chS) = open(leafS)
        val (xp, chP) = open(leafP)

        // ABI order of phone.json
        val f = LinkedHashMap<String, JsonElement>()
        f["nonce_hi"] = dec(nonceHi)
        f["nonce_lo"] = dec(nonceLo)
        f["attempt"] = JsonPrimitive(t.attempt)
        f["role_b"] = JsonPrimitive(roleB)
        f["code_commit"] = dec(codeFr)
        f["issuer"] = JsonArray(iss.map { dec(it) })
        f["sr"] = JsonPrimitive(rate.sr)
        f["valid_at"] = JsonPrimitive(s.validAt)
        f["t"] = u8s(raw)
        f["sig"] = u8s(lowS(s.sig))
        f["exp"] = u8s(s.cred.bytes.copyOfRange(71, 79))
        f["hold"] = u8s(s.cred.holderCommit)
        f["csig"] = u8s(lowS(s.credSig))
        f["salt"] = dec(saltFr)
        f["c_is"] = tpl(s.own.cI)
        f["c_qs"] = tpl(s.own.cQ)
        f["c_ip"] = tpl(s.partner.cI)
        f["c_qp"] = tpl(s.partner.cQ)
        f["xs"] = xs
        f["chs"] = chS
        f["leaf_s"] = JsonPrimitive(leafS.toString())
        f["xp"] = xp
        f["chp"] = chP
        f["leaf_p"] = JsonPrimitive(leafP.toString())
        f["ci"] = JsonArray(List(g.k) { dec(Fr.of(self.i[it])) })
        f["cq"] = JsonArray(List(g.k) { dec(Fr.of(self.q[it])) })
        f["u"] = JsonArray(List(g.k) { JsonPrimitive(it < ja) })

        val hc = OaHash.halfCommit(nonceHi, nonceLo, t.attempt, roleB, rate.sr.toLong(), t.half.toLong(), saltFr,
            raw.copyOfRange(40, 72), raw.copyOfRange(105, 137))
        val pub = listOf(nonceHi, nonceLo, Fr.of(t.attempt.toLong()), if (roleB) Fr.ONE else Fr.ZERO, codeFr) + iss +
            listOf(Fr.of(rate.sr.toLong()), Fr.of(s.validAt), hc)
        val pubBytes = ByteArray(32 * N_PUBLIC)
        pub.forEachIndexed { i, v -> v.toBytes().copyInto(pubBytes, 32 * i) }
        return Built(circuit, rate.sr, JsonObject(f), hc, pubBytes, s.salt)
    }

    /** Leaves opened per side (oalib NL). */
    const val NL = 13

    /** oa_rate.geometry(sr). */
    class Geometry(val k: Int, val nls: Int, val nlp: Int) {
        companion object {
            fun of(r: Popt2Rate): Geometry {
                val k = 2 * r.delta + 1
                val ns = k + r.L - 1 + 2 * Popt2Rule.HM
                val np = r.L + 2 * Popt2Rule.HM
                return Geometry(k, (1023 + ns + 1023) / 1024, (1023 + np + 1023) / 1024)
            }
        }
    }

    /** Exact I, Q, E for lags lo .. lo+n−1 (oa_rate.curve); x outside the capture is 0. */
    internal class Curve(val i: LongArray, val q: LongArray, val e: LongArray, val cn2: Long, val b: Long) {
        fun pass(j: Int) = Popt2Rule.passes(i[j], q[j], e[j], cn2, b)

        companion object {
            fun of(x: ShortArray, code: Popt2Code, lo: Int, n: Int, r: Popt2Rate): Curve {
                val L = r.L
                val hm = Popt2Rule.HM
                val xs = IntArray(n + L - 1 + 2 * hm) { j -> val idx = lo - hm + j; if (idx in x.indices) x[idx].toInt() else 0 }
                val ny = n + L - 1
                val cs = LongArray(ny + 1)
                for (j in 0 until ny) {
                    var y = 0L
                    for (t in 0 until Popt2Rule.TAPS) y += r.h[t].toLong() * xs[j + t]
                    cs[j + 1] = cs[j] + y * y
                }
                val ii = LongArray(n)
                val qq = LongArray(n)
                val e = LongArray(n)
                for (j in 0 until n) {
                    var sI = 0L
                    var sQ = 0L
                    for (m in 0 until L) {
                        val v = xs[hm + j + m].toLong()
                        sI += code.cI[m] * v
                        sQ += code.cQ[m] * v
                    }
                    ii[j] = sI; qq[j] = sQ; e[j] = cs[j + L] - cs[j]
                }
                return Curve(ii, qq, e, code.cn2, r.B)
            }
        }
    }
}

fun Fr.toDecimal(): String = BigNat.fromBytes(toBytes()).toDecimal()
