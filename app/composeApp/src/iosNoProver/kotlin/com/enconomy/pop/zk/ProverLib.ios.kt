package com.enconomy.pop.zk

/** Build without app/zkprove/dist/ios (app/zkprove/scripts/build_ios.sh): no on-phone proofs. */
actual object ProverLib {
    actual val available: Boolean = false
    actual val loadError: String? = "native prover not in this build (app/zkprove/dist/ios missing at build time)"
    actual fun version(): String = "unavailable"
    actual fun prove(circuitJson: String, inputs: ByteArray, crs: String, vk: String?): ZkProof =
        throw ProverException("Unavailable", loadError!!)
}
