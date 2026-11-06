package com.enconomy.pop.zk

import com.enconomy.pop.TranscriptCodec
import com.enconomy.pop.dsp.DspFixtures
import com.enconomy.pop.dsp.PopRound2
import com.enconomy.pop.dsp.Popt2Code
import com.enconomy.pop.dsp.Popt2Rates
import com.enconomy.pop.dsp.Popt2Rule
import com.enconomy.pop.fromB64
import com.enconomy.pop.hexToBytes
import com.enconomy.pop.readTestResourceBytes
import com.enconomy.pop.sha256
import com.enconomy.pop.toHex
import com.enconomy.pop.zk.ZkVectors.str
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlin.time.TimeSource

/**
 * POPT v2 parity with the spike (optionA-v2 oa_rate / rectree / popt) on the 12 JBL250 field sessions:
 * both roles at 48 kHz, plus the mix mode (B at 44.1 kHz) for 4 of them. Fixtures: zk/popt2 (gen_popt2.py).
 * Per role: a_self, a_partner, p_self, p_partner, self_os_delta, half from [PopRound2] on the app windows
 * and [Popt2Rule] on the fixture windows; code_commit; rec_root (Kotlin leaf hashes of the stored crops,
 * the rest of the tree from the spike's leaves); the signed POPT v2 / POPC v2 bytes re-encoded.
 */
class Popt2ParityTest {
    private class Cap(val x: ShortArray, val have: List<IntRange>, val leaves: List<Fe>, val root: Fe)

    private class Session(val o: JsonObject, val bin: ByteArray) {
        val name = str(o, "session")
        fun blob(b: JsonObject): ByteArray {
            val off = b["off"]!!.jsonPrimitive.int
            return bin.copyOfRange(off, off + b["len"]!!.jsonPrimitive.int)
        }

        fun code(sr: Int, emitter: Char): Popt2Code {
            val c = o["codes"]!!.jsonObject[sr.toString()]!!.jsonObject[emitter.toString()]!!.jsonObject
            return Popt2Code(blob(c["cI"]!!.jsonObject), blob(c["cQ"]!!.jsonObject)).also { assertEquals(c["n"]!!.jsonPrimitive.int, it.n) }
        }

        val caps: Map<String, Cap> = o["captures"]!!.jsonObject.mapValues { (_, v) -> cap(v.jsonObject) }

        private fun cap(c: JsonObject): Cap {
            val n = c["frames"]!!.jsonPrimitive.int
            // gaps get a non-constant filler so the v1 flat-run check doesn't see them; the rule never reads them
            val x = ShortArray(n) { ((it % 3) - 1).toShort() }
            val have = ArrayList<IntRange>()
            fun put(start: Int, pcm: ShortArray) {
                pcm.copyInto(x, start)
                have += start until start + pcm.size
            }
            val s = c["source"]!!.jsonObject
            when (str(s, "src")) {
                "rec" -> put(0, ZkVectors.pcm16(str(ZkVectors.json(str(s, "file")), "pcm16_b64")))
                "dsp" -> put(s["offset"]!!.jsonPrimitive.int, DspFixtures.pcm16(
                    str(DspFixtures.json(str(s, "file"))["listeners"]!!.jsonObject[str(s, "role")]!!.jsonObject, "segment_pcm16_b64")))
                "crops" -> for (cr in s["crops"]!!.jsonArray) {
                    val b = blob(cr.jsonObject)
                    put(cr.jsonObject["start"]!!.jsonPrimitive.int, ShortArray(b.size / 2) {
                        ((b[2 * it].toInt() and 0xff) or (b[2 * it + 1].toInt() shl 8)).toShort()
                    })
                }
                else -> error("source")
            }
            val lb = blob(c["leaves"]!!.jsonObject)
            val leaves = List(lb.size / 32) { Fe.fromBytes(lb.copyOfRange(32 * it, 32 * it + 32)) }
            return Cap(x, have, leaves, Fe.fromHex(str(c, "rec_root")))
        }
    }

    private fun load(s8: String) = Session(ZkVectors.json("popt2/$s8.json"), readTestResourceBytes("zk/popt2/$s8.bin"))

    private val sessions: List<String> by lazy {
        ZkVectors.json("popt2/index.json")["sessions"]!!.jsonArray.map { it.jsonPrimitive.content }
    }

    @Test fun twelveSessions() {
        assertEquals(12, sessions.size)
        var roles = 0
        var treeMs = 0L
        var ruleMs = 0L
        for (s8 in sessions) {
            val s = load(s8)
            val t0 = TimeSource.Monotonic.markNow()
            for ((key, c) in s.caps) checkTree(s8, key, c)
            treeMs += t0.elapsedNow().inWholeMilliseconds
            val t1 = TimeSource.Monotonic.markNow()
            for ((mode, m) in s.o["modes"]!!.jsonObject) {
                for ((r, v) in m.jsonObject["roles"]!!.jsonObject) {
                    checkRole(s, "$s8 $mode $r", r[0], v.jsonObject, str(m.jsonObject, "session_nonce"))
                    roles++
                }
            }
            ruleMs += t1.elapsedNow().inWholeMilliseconds
        }
        println("popt2 parity: $roles roles, rule + codec $ruleMs ms, leaves + roots $treeMs ms")
        assertEquals(32, roles)
    }

    /**
     * Kotlin leaf hashes on 8 of the stored full leaves (every leaf of 3 whole captures is in RecTreeTest),
     * root from the spike's leaves via the Kotlin tree.
     */
    private fun checkTree(s8: String, key: String, c: Cap) {
        val n = c.x.size
        val stored = c.leaves.indices.filter { i ->
            val lo = i * RecTree.LEAF
            val hi = minOf(n, lo + RecTree.LEAF) - 1
            c.have.any { lo >= it.first && hi <= it.last }
        }
        assertTrue(stored.size >= 20, "$s8 $key: only ${stored.size} leaves stored")
        for (q in 0 until 8) {
            val i = stored[q * (stored.size - 1) / 7]
            assertEquals(c.leaves[i], RecTree.leafHash(c.x, i * RecTree.LEAF), "$s8 $key leaf $i")
        }
        assertEquals((n + RecTree.LEAF - 1) / RecTree.LEAF, c.leaves.size)
        assertEquals(c.root, RecTree.fromLeaves(c.leaves).root, "$s8 $key rec_root")
    }

    private fun checkRole(s: Session, what: String, role: Char, v: JsonObject, nonceHex: String) {
        val sr = v["sample_rate"]!!.jsonPrimitive.int
        val rate = Popt2Rates.builtIn[sr]!!
        val c = s.caps[str(v, "capture")]!!
        val other = if (role == 'A') 'B' else 'A'
        val own = s.code(sr, role)
        val partner = s.code(sr, other)
        fun int(k: String) = v[k]!!.jsonPrimitive.int
        val self = v["self"]!!.jsonObject
        val part = v["partner"]!!.jsonObject
        fun win(o: JsonObject, k: String) = o[k]!!.jsonArray.let { it[0].jsonPrimitive.int to it[1].jsonPrimitive.int }
        fun covered(lo: Int, a: Int) = assertTrue(c.have.any { lo - Popt2Rule.HM >= it.first && a + rate.L + Popt2Rule.HM - 1 <= it.last }, "$what crop")

        // fixture windows (the spike's search_self / search_partner)
        val (ls, hs) = win(self, "window")
        covered(ls, int("a_self"))
        val a1 = Popt2Rule.earliest(c.x, own, ls, hs, rate)
        assertEquals(int("a_self"), a1.frame, "$what a_self (fixture window)")
        assertRel(self["score"]!!.jsonPrimitive.double, a1.score, "$what score_self")

        // the app's steps, windows from p_self / p_partner
        val r = PopRound2(c.x, rate, role)
        val st = r.selfCheck(own, int("p_self").toDouble())
        assertIs<PopRound2.Step.SelfOk>(st, "$what $st")
        assertEquals(win(self, "app_window").first until win(self, "app_window").second, r.window(st.pSelf))
        assertEquals(self["app_arrival"]!!.jsonPrimitive.int, st.aSelf, "$what a_self (app window)")
        assertEquals(int("a_self"), st.aSelf)
        assertEquals(int("p_self"), st.pSelf)
        assertEquals(int("self_os_delta"), st.selfOsDelta)
        val pt = r.measurePartner(partner, int("p_partner").toDouble())
        assertIs<PopRound2.Step.PartnerOk>(pt, "$what $pt")
        assertEquals(win(part, "window"), win(part, "app_window"))
        covered(win(part, "window").first, pt.aPartner)
        assertEquals(int("a_partner"), pt.aPartner, "$what a_partner")
        assertEquals(int("p_partner"), pt.pPartner)
        assertEquals(int("half"), pt.half, "$what half")
        assertRel(part["score"]!!.jsonPrimitive.double, r.partner!!.score, "$what score_partner")
        assertEquals(int("delta"), rate.delta)
        assertEquals(abs(st.selfOsDelta) <= rate.delta, r.provable, "$what provable")

        // code_commit, rec_root and the signed bytes
        val cc = CodeCommit.compute(own.cI, own.cQ, partner.cI, partner.cQ)
        assertEquals(str(v, "code_commit"), cc.toHex(), "$what code_commit")
        assertEquals(c.root, Fe.fromHex(str(v, "rec_root")))
        val raw = str(v, "transcript_b64").fromB64()
        val t = TranscriptCodec.decodeTranscript2(raw)
        assertEquals(role, t.role)
        assertEquals(sr, t.sampleRate)
        assertEquals(pt.half, t.half)
        assertEquals(st.aSelf, t.aSelf)
        assertEquals(st.pSelf, t.pSelf)
        assertEquals(pt.pPartner, t.pPartner)
        assertEquals(pt.aPartner, t.aPartner)
        assertEquals(st.selfOsDelta, t.selfOsDelta)
        assertEquals(rate.delta, t.delta)
        assertContentEquals(cc, t.codeCommit)
        assertContentEquals(c.root.toBytes(), t.recRoot)
        assertContentEquals(str(v, "pubkey").hexToBytes(), t.pkSelf)
        assertContentEquals(nonceHex.hexToBytes(), t.sessionNonce)
        assertContentEquals(raw, t.encode(), "$what POPT v2 re-encode")
        val commit = str(v, "commit_b64").fromB64()
        assertContentEquals(commit, TranscriptCodec.commit(role, t.attempt, t.sessionNonce, c.root.toBytes(), version = 2), "$what POPC v2")
        assertContentEquals(sha256(commit), t.commitHash)
    }

    private fun assertRel(want: Double, got: Double, what: String) =
        assertTrue(abs(want - got) <= 1e-6 * want, "$what: $want vs $got")
}
