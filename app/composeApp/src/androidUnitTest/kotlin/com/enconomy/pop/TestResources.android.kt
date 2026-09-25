package com.enconomy.pop

actual fun readTestResource(path: String): String {
    val s = Thread.currentThread().contextClassLoader?.getResourceAsStream(path)
        ?: error("test resource not found: $path")
    return s.use { it.readBytes().decodeToString() }
}
