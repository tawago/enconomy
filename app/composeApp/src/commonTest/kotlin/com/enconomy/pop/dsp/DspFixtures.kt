package com.enconomy.pop.dsp

import com.enconomy.pop.fromB64
import com.enconomy.pop.readTestResource
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.abs
import kotlin.math.max
import kotlin.test.assertTrue

/** Loads commonTest/resources/dsp (written by tools/dsp-fixtures/make_fixtures.py). */
object DspFixtures {
    fun json(name: String): JsonObject = Json.parseToJsonElement(readTestResource("dsp/$name")).jsonObject

    val names: List<String> by lazy { json("index.json")["fixtures"]!!.jsonArray.map { it.jsonPrimitive.content } }
    val fixtures: List<Fixture> by lazy { names.map { Fixture(json("$it.json")) } }

    fun pcm16(b64: String): ShortArray {
        val b = b64.fromB64()
        return ShortArray(b.size / 2) { ((b[2 * it].toInt() and 0xff) or (b[2 * it + 1].toInt() shl 8)).toShort() }
    }

    fun f32(b64: String): DoubleArray {
        val b = b64.fromB64()
        return DoubleArray(b.size / 4) { Float.fromBits(le32(b, 4 * it)).toDouble() }
    }

    fun f64(b64: String): DoubleArray {
        val b = b64.fromB64()
        return DoubleArray(b.size / 8) {
            val lo = le32(b, 8 * it).toLong() and 0xffffffffL
            val hi = le32(b, 8 * it + 4).toLong() and 0xffffffffL
            Double.fromBits((hi shl 32) or lo)
        }
    }

    private fun le32(b: ByteArray, o: Int) = (b[o].toInt() and 0xff) or ((b[o + 1].toInt() and 0xff) shl 8) or
        ((b[o + 2].toInt() and 0xff) shl 16) or ((b[o + 3].toInt() and 0xff) shl 24)

    fun doubles(e: JsonElement?): DoubleArray = e!!.jsonArray.map { it.jsonPrimitive.double }.toDoubleArray()

    fun optDouble(e: JsonElement?): Double? = if (e == null || e is JsonNull) null else e.jsonPrimitive.double
    fun optInt(e: JsonElement?): Int? = if (e == null || e is JsonNull) null else e.jsonPrimitive.int
    fun optString(e: JsonElement?): String? = if (e == null || e is JsonNull) null else (e as JsonPrimitive).content

    fun assertRel(expected: Double, actual: Double, rel: Double, what: String, absFloor: Double = 0.0) {
        val tol = max(rel * abs(expected), absFloor)
        assertTrue(abs(expected - actual) <= tol, "$what: expected $expected got $actual (tol $tol)")
    }

    class Window(val kind: String, val emitter: Char, val expected: Double, val template: DoubleArray, val expect: JsonObject)

    class Listener(val role: Char, o: JsonObject) {
        val sr = o["sr"]!!.jsonPrimitive.int
        val capture = pcm16(o["segment_pcm16_b64"]!!.jsonPrimitive.content)
        val expect = o["expect"]!!.jsonObject
        val windows: List<Window> = listOf("self", "partner").map { k ->
            val w = o["windows"]!!.jsonObject[k]!!.jsonObject
            Window(k, w["emitter"]!!.jsonPrimitive.content[0], w["expected"]!!.jsonPrimitive.double,
                f32(w["template_f32_b64"]!!.jsonPrimitive.content), expect[k]!!.jsonObject)
        }
        val flatRuns: List<IntRange> = expect["flat_runs"]!!.jsonArray.map {
            val a = it.jsonArray
            a[0].jsonPrimitive.int until a[1].jsonPrimitive.int
        }
        val glitch = expect["glitch"]!!.jsonPrimitive.boolean
        val glitchSelf = expect["glitch_self"]!!.jsonPrimitive.boolean
        val half = optInt(expect["half"])
    }

    class Fixture(o: JsonObject) {
        val name = o["name"]!!.jsonPrimitive.content
        val sessionIdHex = o["session_id_hex"]!!.jsonPrimitive.content
        val attempt = o["attempt"]!!.jsonPrimitive.int
        val listeners: Map<Char, Listener> = o["listeners"]!!.jsonObject.entries.associate { (k, v) -> k[0] to Listener(k[0], v.jsonObject) }
        val flightCm = optDouble(o["expect_flight_cm"])
        val verdict = optString(o["expect_verdict"])
    }

    /** Correlations shared by the parity tests (computed once per JVM). */
    private val corrCache = HashMap<String, WindowCorr?>()

    fun corr(f: Fixture, l: Listener, w: Window): WindowCorr? = corrCache.getOrPut("${f.name}|${l.role}|${w.kind}") {
        PopDsp.correlate(l.capture, l.sr, w.template, PopDsp.nullTemplates(f.sessionIdHex, w.emitter, f.attempt, l.sr), w.expected)
    }
}
