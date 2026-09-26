package com.enconomy.pop

import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.usePinned
import platform.Foundation.NSData
import platform.Foundation.NSString
import platform.Foundation.NSUTF8StringEncoding
import platform.Foundation.dataWithContentsOfFile
import platform.Foundation.stringWithContentsOfFile
import platform.posix.memcpy

/** The simulator process sees the host FS, so read the source tree directly. */
@OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)
actual fun readTestResource(path: String): String =
    NSString.stringWithContentsOfFile("$TEST_RESOURCE_DIR/$path", NSUTF8StringEncoding, null)
        ?: error("test resource not found: $path")

@OptIn(ExperimentalForeignApi::class)
actual fun readTestResourceBytes(path: String): ByteArray {
    val d = NSData.dataWithContentsOfFile("$TEST_RESOURCE_DIR/$path") ?: error("test resource not found: $path")
    val n = d.length.toInt()
    val out = ByteArray(n)
    if (n > 0) out.usePinned { memcpy(it.addressOf(0), d.bytes, d.length) }
    return out
}
