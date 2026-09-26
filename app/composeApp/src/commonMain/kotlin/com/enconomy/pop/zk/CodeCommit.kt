package com.enconomy.pop.zk

import com.enconomy.pop.sha256

/**
 * code_commit (POPT v2 [279:311]) = SHA-256("pop-code-v2" ‖ cI_self ‖ cQ_self ‖ cI_partner ‖ cQ_partner),
 * each an int8 template (one byte per value, index order), all at the signer's sample rate.
 * "self" = the signer's own emitter's code, "partner" = the other role's (spike oa_rate.code_commit).
 */
object CodeCommit {
    val TAG: ByteArray = "pop-code-v2".encodeToByteArray()

    fun compute(cISelf: ByteArray, cQSelf: ByteArray, cIPartner: ByteArray, cQPartner: ByteArray): ByteArray {
        val l = cISelf.size
        require(l > 0 && cQSelf.size == l && cIPartner.size == l && cQPartner.size == l) { "template lengths differ" }
        return sha256(TAG + cISelf + cQSelf + cIPartner + cQPartner)
    }
}
