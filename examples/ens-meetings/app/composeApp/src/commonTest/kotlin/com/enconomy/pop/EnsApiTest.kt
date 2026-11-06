package com.enconomy.pop

import kotlin.test.Test
import kotlin.test.assertEquals

/** Expected strings come from the backend's claim_message (examples/ens-meetings/backend/main.py). */
class EnsApiTest {
    @Test fun claimMessage() = assertEquals(
        "ens-claim-v1\n{\"device_id\":\"00112233445566778899aabbccddeeff\",\"label\":\"alice-1\",\"ts\":1762400000000}",
        ensClaimMessage("00112233445566778899aabbccddeeff", "alice-1", 1762400000000L).decodeToString(),
    )

    @Test fun readMessageHasNullLabel() = assertEquals(
        "ens-claim-v1\n{\"device_id\":\"00112233445566778899aabbccddeeff\",\"label\":null,\"ts\":1762400000000}",
        ensClaimMessage("00112233445566778899aabbccddeeff", null, 1762400000000L).decodeToString(),
    )
}
