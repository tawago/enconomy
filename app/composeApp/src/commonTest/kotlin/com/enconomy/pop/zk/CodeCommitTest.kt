package com.enconomy.pop.zk

import com.enconomy.pop.fromB64
import com.enconomy.pop.toHex
import com.enconomy.pop.zk.ZkVectors.list
import com.enconomy.pop.zk.ZkVectors.str
import kotlin.test.Test
import kotlin.test.assertEquals

/** code_commit parity with oa_rate.code_commit on the fixtures' signed POPT v2 bytes. */
class CodeCommitTest {
    @Test fun fixtures() {
        val v = ZkVectors.json("code_commit.json")
        assertEquals("pop-code-v2", str(v, "tag"))
        val cases = list(v, "cases")
        assertEquals(8, cases.size)
        for (c in cases) {
            val got = CodeCommit.compute(
                str(c, "cI_self_b64").fromB64(), str(c, "cQ_self_b64").fromB64(),
                str(c, "cI_partner_b64").fromB64(), str(c, "cQ_partner_b64").fromB64(),
            )
            assertEquals(str(c, "code_commit"), got.toHex(), "${str(c, "fixture")} ${str(c, "role")}")
        }
    }
}
