package com.enconomy.pop

/** Reads src/commonTest/resources/<path> (UTF-8). */
expect fun readTestResource(path: String): String

/** Reads src/commonTest/resources/<path> as bytes. */
expect fun readTestResourceBytes(path: String): ByteArray
