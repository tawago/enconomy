package com.enconomy.pop.zk

import com.enconomy.pop.zk.ZkVectors.fe
import com.enconomy.pop.zk.ZkVectors.fes
import com.enconomy.pop.zk.ZkVectors.list
import com.enconomy.pop.zk.ZkVectors.str
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withContext
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.time.TimeSource

/** Parity with rectree.py / p7.py leaf packing, on synthetic signals and real JBL250 captures. */
class RecTreeTest {
    private val v = ZkVectors.p7

    private fun synth(n: Int, mul: Int) = ShortArray(n) { (((mul.toLong() * it) % 65536) - 32768).toInt().toShort() }

    @Test fun packAndLeaf() {
        for (c in list(v, "pack_leaf")) {
            val x = ZkVectors.pcm16(str(c, "pcm16_b64"))
            assertEquals(fes(c["packed"]!!), RecTree.packLeaf(x, 0))
        }
        for (c in list(v, "leaf_hash")) {
            val x = ZkVectors.pcm16(str(c, "pcm16_b64"))
            assertEquals(fe(c["out"]!!), RecTree.leafHash(x, 0))
        }
        // Samples past the end pack as sample 0 (u = 32768), not field 0.
        assertEquals(RecTree.zeroNodes[0], RecTree.leafHash(ShortArray(10), 0))
        assertEquals("0000800080008000800080008000800080008000800080008000800080008000", RecTree.packLeaf(ShortArray(0), 0)[0].toHex())
        assertEquals("0000000000000000000000000000000000000000000000008000800080008000", RecTree.packLeaf(ShortArray(0), 0)[68].toHex())
    }

    @Test fun zeroNodes() {
        assertEquals(fes(v["zero_nodes"]!!), RecTree.zeroNodes)
    }

    @Test fun synthetic() {
        val cases = list(v, "rec_root")
        assertEquals(6, cases.size)
        for (c in cases) {
            val t = RecTree.build(synth(c["n"]!!.jsonPrimitive.int, c["mul"]!!.jsonPrimitive.int))
            assertEquals(fe(c["root"]!!), t.root)
            val path = c["path"]!!.jsonArray.map(::fes)
            assertEquals(path, t.path(c["path_leaf"]!!.jsonPrimitive.int))
        }
    }

    @Test fun realCaptures() {
        for (name in ZkVectors.captures) {
            val c = ZkVectors.json(name)
            val x = ZkVectors.pcm16(str(c, "pcm16_b64"))
            assertEquals(c["frames"]!!.jsonPrimitive.int, x.size)
            val mark = TimeSource.Monotonic.markNow()
            val t = RecTree.build(x)
            val ms = mark.elapsedNow().inWholeMilliseconds
            println("rec_root $name: ${x.size} samples, ${t.levels[0].size} leaves, $ms ms")
            assertEquals(str(c, "rec_root"), t.rootBytes().let { Fe.fromBytes(it).toHex() })
            val levels = c["levels"]!!.jsonArray.map(::fes)
            assertEquals(levels, t.levels)
            for ((k, p) in c["paths"]!!.jsonObject) assertEquals(p.jsonArray.map(::fes), t.path(k.toInt()))
        }
    }

    @Test fun parallelMatches() = runTest {
        val c = ZkVectors.json(ZkVectors.captures[0])
        val x = ZkVectors.pcm16(str(c, "pcm16_b64"))
        RecTree.build(x) // warm-up
        val m1 = TimeSource.Monotonic.markNow()
        val seq = RecTree.build(x)
        val tSeq = m1.elapsedNow().inWholeMilliseconds
        val m2 = TimeSource.Monotonic.markNow()
        val par = withContext(Dispatchers.Default) { RecTree.buildParallel(x, 4) }
        val tPar = m2.elapsedNow().inWholeMilliseconds
        println("rec_root 48k warm: sequential $tSeq ms, 4 workers $tPar ms")
        assertEquals(seq.levels, par.levels)
        assertEquals(str(c, "rec_root"), par.root.toHex())
        assertEquals(RecTree.zeroNodes[RecTree.DEPTH], RecTree.buildParallel(ShortArray(0)).root)
    }
}
