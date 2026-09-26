package com.enconomy.pop

/** Reads src/commonTest/resources/<path> (UTF-8). */
expect fun readTestResource(path: String): String

/** Reads src/commonTest/resources/<path> as bytes. */
expect fun readTestResourceBytes(path: String): ByteArray

/** Writable scratch directory for tests. */
expect fun testTempDir(): String

/** Environment variable of the test process (iOS simulator: passed as SIMCTL_CHILD_<name> by gradle). */
expect fun testEnv(name: String): String?

/** App files bundled as Compose resources (src/commonMain/composeResources/<path>). */
fun readComposeResource(path: String): String =
    runCatching { readTestResource(path) }.getOrElse { readTestResource("../../commonMain/composeResources/$path") }
