package com.enconomy.pop.zk

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope

/**
 * Option-A (Noir) hashes, bit for bit as research/worldid/prototypes/optA-noir/noir/oalib/src/lib.nr:
 * the Sp sponge (rate 3, tag in s[3]), leaf_hash, node_hash, the depth-4 rec tree, code_commitment and the
 * half commitment. Mirrors server/pop/poseidon2.py; both are checked against nargo output (zkmobile/hash/).
 */
object OaHash {
    val TAG_LEAF: Fr = Fr.of(262145) // 1 + (1024 << 8)
    val TAG_NODE: Fr = Fr.of(2)
    val TAG_HALF: Fr = Fr.of(8)
    val TAG_FS: Fr = Fr.of(101897)
    val TAG_CODE: Fr = Fr.of(10)
    const val L = 12000
    const val LEAF = 1024
    const val NLEAVES = 256
    const val CAP = NLEAVES * LEAF

    /**
     * oalib Sp: s = [0, 0, 0, tag]; absorb adds into s[pos] and permutes after every 3rd element; finish permutes
     * only if pos != 0 (a multiple-of-3 length gets no extra permutation; empty input returns s[0] = 0).
     */
    class Sp(tag: Fr, private val p: Poseidon2Bn = Poseidon2Bn()) {
        private val s = LongArray(4 * Bn254.N).also { tag.m.copyInto(it, 3 * Bn254.N) }
        private var pos = 0

        fun absorb(x: Fr) = absorbMont(x.m, 0)

        internal fun absorbMont(x: LongArray, xo: Int) {
            val o = pos * Bn254.N
            Bn254.add(s, o, s, o, x, xo)
            pos++
            if (pos == 3) {
                p.permute(s)
                pos = 0
            }
        }

        fun finish(): Pair<Fr, Fr> {
            if (pos != 0) {
                p.permute(s)
                pos = 0
            }
            return Fr(s.copyOfRange(0, Bn254.N)) to Fr(s.copyOfRange(Bn254.N, 2 * Bn254.N))
        }
    }

    fun hashN(tag: Fr, xs: List<Fr>, p: Poseidon2Bn = Poseidon2Bn()): Fr {
        val sp = Sp(tag, p)
        for (x in xs) sp.absorb(x)
        return sp.finish().first
    }

    /** leaf over 1,024 offset samples u = x + 32768 (0..65535): 69 elements of 15 x 16 bits, little-end. */
    fun leafHashU(u: IntArray, off: Int = 0, p: Poseidon2Bn = Poseidon2Bn()): Fr {
        val sp = Sp(TAG_LEAF, p)
        val c = LongArray(Bn254.N)
        val t = LongArray(Bn254.N + 2)
        for (k in 0 until 69) {
            c.fill(0L)
            for (j in 0 until 15) {
                val idx = 15 * k + j
                if (idx >= LEAF) break
                val v = (u[off + idx] and 0xFFFF).toLong()
                val bit = 16 * j
                c[bit / 32] = c[bit / 32] or (v shl (bit % 32))
            }
            Bn254.toMont(c, 0, t)
            sp.absorbMont(c, 0)
        }
        return sp.finish().first
    }

    /** leaf over 1,024 signed int16 samples starting at [off]; samples past x.size count as 0. */
    fun leafHash(x: ShortArray, off: Int, p: Poseidon2Bn = Poseidon2Bn()): Fr {
        val u = IntArray(LEAF) { i -> (if (off + i < x.size) x[off + i].toInt() else 0) + 32768 }
        return leafHashU(u, 0, p)
    }

    fun nodeHash(c: List<Fr>, p: Poseidon2Bn = Poseidon2Bn()): Fr {
        require(c.size == 4)
        return hashN(TAG_NODE, c, p)
    }

    /**
     * rec tree over a capture of int16 samples (size <= 262,144), zero-padded to 256 leaves as gen_inputs.py
     * (padding sample 0 -> u = 32768, every leaf hashed, no null nodes). levels = [256 leaves, 64, 16, 4, 1].
     */
    class RecTree2 internal constructor(val levels: List<List<Fr>>) {
        val root: Fr get() = levels.last()[0]
        fun rootBytes(): ByteArray = root.toBytes()

        /** the 4 sibling groups of leaf [idx], bottom up (chs / chp row). */
        fun path(idx: Int): List<List<Fr>> {
            var i = idx
            return List(4) { l ->
                val b = (i / 4) * 4
                i /= 4
                levels[l].subList(b, b + 4)
            }
        }
    }

    fun recTree(x: ShortArray): RecTree2 {
        require(x.size <= CAP) { "capture too long: ${x.size}" }
        val p = Poseidon2Bn()
        var zeroLeaf: Fr? = null
        val leaves = List(NLEAVES) { i ->
            val lo = i * LEAF
            val silent = lo >= x.size || (lo + LEAF > x.size && (lo until x.size).all { x[it].toInt() == 0 })
            if (silent) zeroLeaf ?: leafHash(ShortArray(0), 0, p).also { zeroLeaf = it } else leafHash(x, lo, p)
        }
        val levels = mutableListOf(leaves)
        while (levels.last().size > 1) {
            val c = levels.last()
            levels.add(List(c.size / 4) { j -> nodeHash(c.subList(4 * j, 4 * j + 4), p) })
        }
        return RecTree2(levels)
    }

    fun recRoot(x: ShortArray): Fr = recTree(x).root

    /** [recTree] with the leaves hashed on [workers] coroutines of Dispatchers.Default. */
    suspend fun recTreeParallel(x: ShortArray, workers: Int = 4): RecTree2 = coroutineScope {
        require(x.size <= CAP) { "capture too long: ${x.size}" }
        val parts = (0 until NLEAVES).chunked((NLEAVES + workers - 1) / workers).map { idx ->
            async(Dispatchers.Default) {
                val p = Poseidon2Bn()
                idx.map { i -> if (i * LEAF >= x.size) null else leafHash(x, i * LEAF, p) }
            }
        }
        val p = Poseidon2Bn()
        val zero = leafHash(ShortArray(0), 0, p)
        val levels = mutableListOf(parts.awaitAll().flatten().map { it ?: zero })
        while (levels.last().size > 1) {
            val c = levels.last()
            levels.add(List(c.size / 4) { j -> nodeHash(c.subList(4 * j, 4 * j + 4), p) })
        }
        RecTree2(levels)
    }

    /** code commitment over four u8 templates (u8 = v + 128, bytes read unsigned), L each; 31 B / element, BE. */
    fun codeCommitmentU8(a: ByteArray, b: ByteArray, c: ByteArray, d: ByteArray): Fr {
        val sp = Sp(TAG_CODE)
        for (tpl in listOf(a, b, c, d)) {
            require(tpl.size == L)
            var k = 0
            while (k < L) {
                val n = minOf(31, L - k)
                sp.absorb(Fr.fromBytesSmall(tpl, k, n))
                k += 31
            }
        }
        return sp.finish().first
    }

    /** same over int8 templates (signed Kotlin bytes, -128..127): u8 = v + 128. */
    fun codeCommitment(cIs: ByteArray, cQs: ByteArray, cIp: ByteArray, cQp: ByteArray): Fr {
        fun u8(t: ByteArray) = ByteArray(t.size) { (t[it] + 128).toByte() }
        return codeCommitmentU8(u8(cIs), u8(cQs), u8(cIp), u8(cQp))
    }

    /** 32-byte X coordinate -> [hi128, lo128] big-endian limbs. */
    fun xLimbs(x: ByteArray): List<Fr> {
        require(x.size == 32)
        return listOf(Fr.fromBytesSmall(x, 0, 16), Fr.fromBytesSmall(x, 16, 16))
    }

    /** hash_n(TAG_HALF, [nonce_hi, nonce_lo, attempt, role_b, sr, half, salt, X_own hi, lo, X_partner hi, lo]). */
    fun halfCommit(
        nonceHi: Fr, nonceLo: Fr, attempt: Int, roleB: Boolean, sr: Long, half: Long, salt: Fr,
        xOwn: ByteArray, xPartner: ByteArray,
    ): Fr = hashN(
        TAG_HALF,
        listOf(nonceHi, nonceLo, Fr.of(attempt.toLong()), if (roleB) Fr.ONE else Fr.ZERO, Fr.of(sr), Fr.of(half), salt) +
            xLimbs(xOwn) + xLimbs(xPartner),
    )

    // ---- holder_commit: oalib has no definition. Two conventions exist in the prototypes; neither is picked here.

    /**
     * opt3 prototype (opt3-noir-p256 hashhelper / poplib): noir-lang/poseidon v0.3.0 Poseidon2::hash([secret], 1),
     * a sponge with IV = 1 << 64 in s[3]: s[0] += secret, one permutation, s[0].
     */
    fun holderCommitOpt3(secret: Fr): Fr = hashN(Fr.fromHex("10000000000000000"), listOf(secret))

    /** oalib-Sp style: hash_n(tag, [secret]). oalib defines no holder tag; the caller chooses it. */
    fun holderCommitSp(secret: Fr, tag: Fr): Fr = hashN(tag, listOf(secret))
}
