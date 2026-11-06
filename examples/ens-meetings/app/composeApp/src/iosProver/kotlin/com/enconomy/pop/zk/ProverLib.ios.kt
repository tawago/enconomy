@file:OptIn(ExperimentalForeignApi::class)

package com.enconomy.pop.zk

import com.enconomy.pop.zk.native.ZkBuf
import com.enconomy.pop.zk.native.zk_buf_free
import com.enconomy.pop.zk.native.zk_prove
import com.enconomy.pop.zk.native.zk_version
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.UByteVar
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr as addr
import kotlinx.cinterop.readBytes
import kotlinx.cinterop.readValue
import kotlinx.cinterop.reinterpret
import kotlinx.cinterop.toKString
import kotlinx.cinterop.usePinned

/** libzkprove.a from app/zkprove/dist/ios (cinterop zkprove.def). */
actual object ProverLib {
    actual val available: Boolean = true
    actual val loadError: String? = null

    actual fun version(): String = zk_version()?.toKString() ?: "?"

    actual fun prove(circuitJson: String, inputs: ByteArray, crs: String, vk: String?): ZkProof = memScoped {
        val proof = alloc<ZkBuf>()
        val pubs = alloc<ZkBuf>()
        val err = alloc<ZkBuf>()
        val rc = inputs.usePinned { pin ->
            zk_prove(circuitJson, pin.addressOf(0).reinterpret<UByteVar>(), inputs.size.toULong(), crs, vk,
                proof.addr, pubs.addr, err.addr)
        }
        if (rc != 0) throw ProverException.ofRc(rc, take(err).decodeToString())
        ZkProof(take(proof), take(pubs))
    }

    private fun take(b: ZkBuf): ByteArray {
        val p = b.ptr ?: return ByteArray(0)
        val out = p.readBytes(b.len.toInt())
        zk_buf_free(b.readValue())
        return out
    }
}
