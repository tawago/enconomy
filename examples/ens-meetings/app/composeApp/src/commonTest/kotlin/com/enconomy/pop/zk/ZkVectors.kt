package com.enconomy.pop.zk

import com.enconomy.pop.fromB64
import com.enconomy.pop.readTestResource
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Loads commonTest/resources/zk (written by zk/tools/gen_vectors.py from the spike python). */
object ZkVectors {
    fun json(name: String): JsonObject = Json.parseToJsonElement(readTestResource("zk/$name")).jsonObject

    val p7: JsonObject by lazy { json("p7_vectors.json") }

    val captures = listOf("rec_180ca04b_48k_A.json", "rec_180ca04b_48k_B.json", "rec_2940913c_mix_B.json")

    fun fe(e: JsonElement): Fe = Fe.fromHex(e.jsonPrimitive.content)
    fun fes(e: JsonElement): List<Fe> = e.jsonArray.map(::fe)
    fun str(o: JsonObject, k: String): String = o[k]!!.jsonPrimitive.content
    fun list(o: JsonObject, k: String): List<JsonObject> = o[k]!!.jsonArray.map { it.jsonObject }

    fun pcm16(b64: String): ShortArray {
        val b = b64.fromB64()
        return ShortArray(b.size / 2) { ((b[2 * it].toInt() and 0xff) or (b[2 * it + 1].toInt() shl 8)).toShort() }
    }
}
