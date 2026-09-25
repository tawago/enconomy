package com.enconomy.pop

import kotlinx.cinterop.BetaInteropApi
import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSString
import platform.Foundation.NSUTF8StringEncoding
import platform.Foundation.stringWithContentsOfFile

/** The simulator process sees the host FS, so read the source tree directly. */
@OptIn(ExperimentalForeignApi::class, BetaInteropApi::class)
actual fun readTestResource(path: String): String =
    NSString.stringWithContentsOfFile("$TEST_RESOURCE_DIR/$path", NSUTF8StringEncoding, null)
        ?: error("test resource not found: $path")
