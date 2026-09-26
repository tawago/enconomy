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
    val tree: RecTree.Tree? = null,
)

class UnprovableException(val reason: String, msg: String) : Exception("$reason: $msg")

/**
 * Witness input of oa2t_s48 / oa2t_s44 (spike optionA-v2/prep_popt2.py build_phone, port spec §5.3).
 * Transcript fields are sliced from the signed bytes, so the witness is exactly what the key signed.
 * Before building, the circuit's conditions are re-checked here (integer rule at a_self and a_partner,
 * |self_os_delta| ≤ delta, geometry, code_commit, rec_root, credential), so a doomed proof is refused
 * in milliseconds instead of after the native witness.
 */
object WitnessInput {
    const val TAG_HALF2 = 8L

    class Built(
        val circuit: String,
        val sampleRate: Int,
        val fields: JsonObject,
        /** halfCommit = public[0] of the proof. */
        val halfCommit: Fe,
        /** The public vector an honest verifier derives (outputs first). */
        val expectedPublic: List<String>,
        val salt: ByteArray,
    ) {
        val json: String by lazy { fields.toString() }
    }

    fun circuitFor(sr: Int): String? = if (sr in Popt2Rates.builtIn) "oa2t_s${sr / 1000}" else null

    fun build(s: ProofSource): Built {
        fun no(reason: String, msg: String): Nothing = throw UnprovableException(reason, msg)
        val raw = s.transcript
        val t = runCatching { TranscriptCodec.decodeTranscript2(raw) }.getOrElse { no("bad_transcript", it.message ?: "") }
        val rate = Popt2Rates.builtIn[t.sampleRate] ?: no("no_circuit", "no circuit for ${t.sampleRate} Hz")
        val circuit = circuitFor(rate.sr)!!
        val L = rate.L
        val hm = Popt2Rule.HM
        if (t.delta != rate.delta) no("bad_transcript", "delta ${t.delta} != ${rate.delta}")
        if (s.sig.size != 64 || s.credSig.size != 64) no("bad_sig", "signatures must be raw r||s")
        if (s.salt.size != 31) no("bad_salt", "salt must be 31 bytes")
        if (s.own.n != L || s.partner.n != L) no("bad_code", "code length != $L")
        if (raw[39] != 4.toByte() || raw[104] != 4.toByte()) no("bad_transcript", "pubkeys must be SEC1 uncompressed")
        if (!s.cred.devicePub64.contentEquals(raw.copyOfRange(40, 104))) no("wrong_credential", "credential is for another key")
        if (s.cred.expiry < s.validAt) no("credential_expired", "credential expiry ${s.cred.expiry} < validAt ${s.validAt}")
        if (s.issuerPub.size != 65 || s.issuerPub[0] != 4.toByte()) no("bad_issuer", "issuer pub must be 04||X||Y")
        if (!CodeCommit.compute(s.own.cI, s.own.cQ, s.partner.cI, s.partner.cQ).contentEquals(t.codeCommit)) {
            no("code_commit", "codes do not match the signed code_commit")
        }
        val tree = s.tree ?: RecTree.build(s.capture)
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
        val leafS = (lo - hm) / RecTree.LEAF
        val leafP = (aPartner - hm) / RecTree.LEAF
        if (leafS + g.nls > RecTree.NLEAVES || leafP + g.nlp > RecTree.NLEAVES) no("geometry", "window past the tree")
        if (aSelf - lo !in 0 until g.k) no("self_os_delta", "a_self $aSelf outside the self window from $lo (${g.k} samples)")

        val self = Curve.of(s.capture, s.own, lo, g.k, rate)
        val ja = aSelf - lo
        for (j in 0 until ja) if (self.pass(j)) no("self_rule", "own code passes at ${lo + j}, before a_self $aSelf")
        if (!self.pass(ja)) no("self_rule", "own code does not pass at a_self $aSelf")
        if (!Curve.of(s.capture, s.partner, aPartner, 1, rate).pass(0)) no("partner_rule", "partner code does not pass at a_partner $aPartner")

        val nonce = t.sessionNonce
        val nonceHi = BigNat.fromBytes(nonce.copyOfRange(0, 16))
        val nonceLo = BigNat.fromBytes(nonce.copyOfRange(16, 32))
        val roleB = if (t.role == 'B') 1L else 0L
        val cc = t.codeCommit
        val codeHi = BigNat.fromBytes(cc.copyOfRange(0, 16))
        val codeLo = BigNat.fromBytes(cc.copyOfRange(16, 32))
        val issX = BigNat.fromBytes(s.issuerPub.copyOfRange(1, 33))
        val issY = BigNat.fromBytes(s.issuerPub.copyOfRange(33, 65))

        val dec = FeDec()
        fun codeArr(b: ByteArray) = JsonArray(List(b.size) { JsonPrimitive(dec.of(b[it].toLong())) })
        fun bytesArr(from: Int, to: Int) = JsonArray(List(to - from) { JsonPrimitive(raw[from + it].toInt() and 0xff) })
        fun bytesOf(b: ByteArray) = JsonArray(List(b.size) { JsonPrimitive(b[it].toInt() and 0xff) })
        fun str(v: Any) = JsonPrimitive(v.toString())
        fun open(first: Int, n: Int): Pair<JsonArray, JsonArray> {
            val xs = ArrayList<JsonElement>(n)
            val ch = ArrayList<JsonElement>(n)
            for (i in 0 until n) {
                val leaf = first + i
                val a = leaf * RecTree.LEAF
                xs.add(JsonArray(List(RecTree.LEAF) { k ->
                    val idx = a + k
                    JsonPrimitive(dec.of(if (idx < s.capture.size) s.capture[idx].toLong() else 0L))
                }))
                ch.add(JsonArray(tree.path(leaf).map { lvl -> JsonArray(lvl.map { JsonPrimitive(it.toDecimal()) }) }))
            }
            return JsonArray(xs) to JsonArray(ch)
        }

        val sigR = BigNat.fromBytes(s.sig.copyOfRange(0, 32))
        val sigS = BigNat.fromBytes(s.sig.copyOfRange(32, 64))
        val credR = BigNat.fromBytes(s.credSig.copyOfRange(0, 32))
        val credS = BigNat.fromBytes(s.credSig.copyOfRange(32, 64))
        val salt = BigNat.fromBytes(s.salt)
        val (xs, chS) = open(leafS, g.nls)
        val (xp, chP) = open(leafP, g.nlp)
        val cIs = codeArr(s.own.cI)
        val cQs = codeArr(s.own.cQ)
        val cIp = codeArr(s.partner.cI)
        val cQp = codeArr(s.partner.cQ)

        val f = LinkedHashMap<String, JsonElement>()
        f["ownPub"] = bytesArr(40, 104)
        f["partnerPub"] = bytesArr(105, 169)
        f["halfBytes"] = bytesArr(173, 177)
        f["recBytes"] = bytesArr(177, 209)
        f["pfpB"] = bytesArr(209, 217)
        f["pntB"] = bytesArr(217, 225)
        f["rf0B"] = bytesArr(225, 233)
        f["sodB"] = bytesArr(233, 237)
        f["chB"] = bytesArr(237, 269)
        f["aSelfB"] = bytesArr(269, 273)
        f["pPartnerB"] = bytesArr(273, 277)
        f["deltaB"] = bytesArr(277, 279)
        f["nonceHi"] = str(nonceHi)
        f["nonceLo"] = str(nonceLo)
        f["attempt"] = str(t.attempt)
        f["roleB"] = str(roleB)
        f["codeHi"] = str(codeHi)
        f["codeLo"] = str(codeLo)
        f["cIs"] = cIs
        f["cQs"] = cQs
        f["cIp"] = cIp
        f["cQp"] = cQp
        f["issuerX"] = str(issX)
        f["issuerY"] = str(issY)
        f["sr"] = str(rate.sr)
        f["validAt"] = str(s.validAt)
        f["sig_r"] = str(sigR)
        f["sig_sInv"] = str(sigS.modInversePrime(BigNat.N))
        f["exp"] = bytesOf(s.cred.bytes.copyOfRange(71, 79))
        f["cred_r"] = str(credR)
        f["cred_sInv"] = str(credS.modInversePrime(BigNat.N))
        f["holdCommit"] = bytesOf(s.cred.holderCommit)
        f["salt"] = str(salt)
        f["xs"] = xs
        f["chS"] = chS
        f["leafS"] = str(leafS)
        f["xp"] = xp
        f["chP"] = chP
        f["leafP"] = str(leafP)
        f["I"] = JsonArray(List(g.k) { JsonPrimitive(dec.of(self.i[it])) })
        f["Q"] = JsonArray(List(g.k) { JsonPrimitive(dec.of(self.q[it])) })
        f["u"] = JsonArray(List(g.k) { JsonPrimitive(if (it < ja) "1" else "0") })

        val hc = halfCommit(nonce, t.attempt, roleB, rate.sr, t.half, s.salt, raw.copyOfRange(40, 72), raw.copyOfRange(105, 137))
        val pub = ArrayList<String>(1 + 6 + 4 * L + 4)
        pub += hc.toDecimal()
        pub += listOf(nonceHi.toDecimal(), nonceLo.toDecimal(), t.attempt.toString(), roleB.toString(), codeHi.toDecimal(), codeLo.toDecimal())
        for (a in listOf(cIs, cQs, cIp, cQp)) a.forEach { pub += (it as JsonPrimitive).content }
        pub += listOf(issX.toDecimal(), issY.toDecimal(), rate.sr.toString(), s.validAt.toString())
        return Built(circuit, rate.sr, JsonObject(f), hc, pub, s.salt)
    }

    /** sponge16(8, [nonceHi, nonceLo, attempt, roleB, sr, half mod p, salt, X_self, X_partner]) (prep_popt2.half_commit). */
    fun halfCommit(nonce: ByteArray, attempt: Int, roleB: Long, sr: Int, half: Int, salt: ByteArray, xSelf: ByteArray, xPartner: ByteArray): Fe {
        fun fe(b: ByteArray) = Fe.fromBytes(ByteArray(32 - b.size) + b)
        return Poseidon7.hash16(TAG_HALF2, listOf(
            fe(nonce.copyOfRange(0, 16)), fe(nonce.copyOfRange(16, 32)), Fe.of(attempt.toLong()), Fe.of(roleB), Fe.of(sr.toLong()),
            Fe.of(half.toLong()), fe(salt), fe(xSelf), fe(xPartner),
        ))
    }

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

    /** fe(v) as decimal, cached for small values (samples, codes). */
    private class FeDec {
        private val neg = HashMap<Long, String>()
        fun of(v: Long): String = if (v >= 0) v.toString() else neg.getOrPut(v) { (BigNat.P - BigNat.of(-v)).toDecimal() }
    }
}

fun Fe.toDecimal(): String = BigNat.fromBytes(toBytes()).toDecimal()
