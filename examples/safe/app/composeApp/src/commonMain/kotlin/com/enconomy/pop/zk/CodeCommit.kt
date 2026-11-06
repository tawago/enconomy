package com.enconomy.pop.zk

/**
 * code_commit (POPT v2 [279:311]) = oalib code_commitment (Noir option A, onchain variant): Poseidon2 sponge
 * (TAG_CODE = 10) over cI_self ‖ cQ_self ‖ cI_partner ‖ cQ_partner, each int8 template as u8 = v + 128,
 * 31 bytes big-endian per element per template (the last element of a template holds the remainder),
 * 32 bytes big-endian. "self" = the signer's own emitter's code, "partner" = the other role's.
 * Same as OaHash.codeCommitment for L = 12,000 (48 kHz); other rates use their own L with the same packing.
 */
object CodeCommit {
    fun compute(cISelf: ByteArray, cQSelf: ByteArray, cIPartner: ByteArray, cQPartner: ByteArray): ByteArray {
        val l = cISelf.size
        require(l > 0 && cQSelf.size == l && cIPartner.size == l && cQPartner.size == l) { "template lengths differ" }
        val sp = OaHash.Sp(OaHash.TAG_CODE)
        val buf = ByteArray(31)
        for (t in listOf(cISelf, cQSelf, cIPartner, cQPartner)) {
            var k = 0
            while (k < l) {
                val n = minOf(31, l - k)
                for (j in 0 until n) buf[j] = (t[k + j] + 128).toByte()
                sp.absorb(Fr.fromBytesSmall(buf, 0, n))
                k += 31
            }
        }
        return sp.finish().first.toBytes()
    }
}
