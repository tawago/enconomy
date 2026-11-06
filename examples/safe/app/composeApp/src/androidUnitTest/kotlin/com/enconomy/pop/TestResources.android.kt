package com.enconomy.pop

actual fun readTestResource(path: String): String {
    val s = Thread.currentThread().contextClassLoader?.getResourceAsStream(path)
        ?: error("test resource not found: $path")
    return s.use { it.readBytes().decodeToString() }
}

actual fun readTestResourceBytes(path: String): ByteArray {
    val s = Thread.currentThread().contextClassLoader?.getResourceAsStream(path)
        ?: error("test resource not found: $path")
    return s.use { it.readBytes() }
}

actual fun testTempDir(): String = java.nio.file.Files.createTempDirectory("poptest").toString()

actual fun testEnv(name: String): String? = System.getenv(name)
