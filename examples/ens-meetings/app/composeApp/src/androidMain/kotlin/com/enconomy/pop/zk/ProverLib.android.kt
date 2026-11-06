package com.enconomy.pop.zk

/** JNI entry points of app/zkprove/src/jni_android.rs; names must match exactly. */
object ZkProverNative {
    @JvmStatic external fun version(): String
    /** Returns [proof, publicInputs]. */
    @JvmStatic external fun prove(circuitJsonPath: String, inputs: ByteArray, crsPath: String, vkPath: String?): Array<ByteArray>
}

actual object ProverLib {
    /** jniLibs/arm64-v8a/libzkprove.so (gradle copyProverSo); absent on other ABIs. */
    actual val loadError: String? = try {
        System.loadLibrary("zkprove")
        null
    } catch (e: Throwable) {
        "native prover not in this build (${e.message})"
    }

    actual val available: Boolean get() = loadError == null

    actual fun version(): String = if (available) runCatching { ZkProverNative.version() }.getOrDefault("zkprove (jni)") else "unavailable"

    actual fun prove(circuitJson: String, inputs: ByteArray, crs: String, vk: String?): ZkProof {
        loadError?.let { throw ProverException("Unavailable", it) }
        val r = try {
            ZkProverNative.prove(circuitJson, inputs, crs, vk)
        } catch (e: RuntimeException) {
            val m = e.message ?: throw e
            if (!m.startsWith("zkprove: ")) throw e
            val msg = m.removePrefix("zkprove: ")
            val code = when {
                msg.startsWith("acvm") || msg.startsWith("inputs") || msg.startsWith("abi encode") -> "Witness"
                msg.startsWith("prove") -> "Prove"
                else -> "Arg"
            }
            throw ProverException(code, msg)
        }
        return ZkProof(r[0], r[1])
    }
}
