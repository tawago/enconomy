package com.enconomy.pop.zk

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope

/**
 * rec_root for POPT v2: 4-ary Poseidon7 Merkle tree, depth 4, over the int16 capture (spike rectree.py).
 *
 * leaf i    x[1024 i .. 1024 i + 1023]; samples past the capture are sample 0 (packed as u = 32768)
 * pack      u = x + 32768; element m = Σ_{k<15} u[15m + k] · 2^(16k), 69 elements (the last holds 4)
 * leaf      sponge16(TAG_LEAF, 69 elements)[0]
 * node      node5(4 children); missing leaves / subtrees are the zero-sample leaf / zero subtree
 * rec_root  level-4 node 0, 32 bytes big-endian
 */
object RecTree {
    const val LEAF = 1024
    const val PACK = 15
    const val NPACK = (LEAF + PACK - 1) / PACK // 69
    const val DEPTH = 4
    const val NLEAVES = 256 // 4^DEPTH

    /** zeroNodes[l] = root of an all-zero-sample subtree at level l (0 = one zero leaf). */
    val zeroNodes: List<Fe> by lazy {
        val z = mutableListOf(leafHash(ShortArray(0), 0))
        repeat(DEPTH) { val c = z.last(); z.add(Poseidon7.node5(c, c, c, c)) }
        z
    }

    /** Packed leaf elements for x[off .. off + 1023] (past x.size = sample 0). */
    fun packLeaf(x: ShortArray, off: Int): List<Fe> {
        val buf = LongArray(NPACK * Fp.N)
        pack(x, off, buf)
        return List(NPACK) { Fe(buf.copyOfRange(it * Fp.N, (it + 1) * Fp.N)) }
    }

    fun leafHash(x: ShortArray, off: Int): Fe = leafHash(x, off, Poseidon7.Perm(Poseidon7.params(16)), LongArray(NPACK * Fp.N))

    private fun leafHash(x: ShortArray, off: Int, w: Poseidon7.Perm, buf: LongArray): Fe {
        pack(x, off, buf)
        w.absorb(Poseidon7.TAG_LEAF, NPACK, buf)
        return w.cell(1)
    }

    /** Lane k of element m sits in limb k/2, bits 16·(k%2). 15 lanes = 240 bits < p. */
    private fun pack(x: ShortArray, off: Int, buf: LongArray) {
        buf.fill(0L)
        for (s in 0 until LEAF) {
            val i = off + s
            val u = (if (i < x.size) x[i].toLong() else 0L) + 32768L
            val m = s / PACK
            val k = s - m * PACK
            buf[m * Fp.N + (k shr 1)] = buf[m * Fp.N + (k shr 1)] or (u shl (16 * (k and 1)))
        }
    }

    /** levels[l][j] for the real nodes only (level 0 = ceil(n/1024) leaves; level 4 = [root]). */
    class Tree internal constructor(val levels: List<List<Fe>>) {
        val root: Fe get() = levels[DEPTH].getOrNull(0) ?: zeroNodes[DEPTH]

        fun rootBytes(): ByteArray = root.toBytes()

        /** For l = 0 .. DEPTH-1: the 4 children of the parent of the path node (itself included). */
        fun path(leafIdx: Int): List<List<Fe>> {
            require(leafIdx in 0 until NLEAVES)
            var i = leafIdx
            return List(DEPTH) { l ->
                val base = (i / 4) * 4
                i /= 4
                List(4) { k -> levels[l].getOrNull(base + k) ?: zeroNodes[l] }
            }
        }
    }

    /** Whole tree over the capture ([x].size ≤ 262144). About 5 perm16 per leaf, one perm5 per node. */
    fun build(x: ShortArray): Tree {
        val n = leafCount(x)
        val w16 = Poseidon7.Perm(Poseidon7.params(16))
        val buf = LongArray(NPACK * Fp.N)
        return fromLeaves(List(n) { leafHash(x, it * LEAF, w16, buf) })
    }

    /** [build] with the leaves hashed on [workers] coroutines of Dispatchers.Default. */
    suspend fun buildParallel(x: ShortArray, workers: Int = 4): Tree = coroutineScope {
        val n = leafCount(x)
        val step = maxOf(1, (n + workers - 1) / maxOf(1, workers))
        val parts = (0 until n).chunked(step).map { idx ->
            async(Dispatchers.Default) {
                val w16 = Poseidon7.Perm(Poseidon7.params(16))
                val buf = LongArray(NPACK * Fp.N)
                idx.map { leafHash(x, it * LEAF, w16, buf) }
            }
        }
        fromLeaves(parts.awaitAll().flatten())
    }

    private fun leafCount(x: ShortArray): Int {
        val n = (x.size + LEAF - 1) / LEAF
        require(n <= NLEAVES) { "capture too long for the rec tree: ${x.size} samples" }
        return n
    }

    /** Tree over given leaf hashes (level 0). */
    internal fun fromLeaves(leaves: List<Fe>): Tree {
        val levels = mutableListOf(leaves)
        val w5 = Poseidon7.Perm(Poseidon7.params(5))
        for (l in 0 until DEPTH) {
            val cur = levels.last()
            val z = zeroNodes[l].w
            fun at(i: Int) = cur.getOrNull(i)?.w ?: z
            levels.add(List((cur.size + 3) / 4) { j ->
                w5.node(at(4 * j), 0, at(4 * j + 1), 0, at(4 * j + 2), 0, at(4 * j + 3), 0).cell(1)
            })
        }
        return Tree(levels)
    }

    /** rec_root, 32 bytes big-endian (POPT v2 [177:209], POPC v2 [39:71]). */
    fun root(x: ShortArray): ByteArray = build(x).rootBytes()
}
