package com.enconomy.pop

import com.enconomy.pop.dsp.Popt2Rate
import com.enconomy.pop.dsp.Popt2Rates
import com.enconomy.pop.dsp.Popt2Rule
import com.enconomy.pop.zk.RecTree
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * POPT v2 switch (docs/pop-transcript-v2.md). A phone arms with "popt": 2 only when the server offers v2,
 * its v2 constants and per-rate tables equal the app's, and the phone's sample rate has a circuit
 * (48 kHz / 44.1 kHz). Anything else runs pop-v1 unchanged.
 *
 * [selfOsTolMs] is the server's self_os_tol_ms (one value for server and app; §6.1 already checks it
 * equals PopConstants.SELF_OS_TOL_MS).
 */
class Popt2Config(val rates: Map<Int, Popt2Rate>, val selfOsTolMs: Int) {
    fun rate(sr: Int): Popt2Rate? = rates[sr]

    companion object {
        const val DELTA_MS = 2
        const val TEMPLATE_BITS = 8

        /** null = server has no (or a different) v2. */
        fun from(cfg: JsonObject): Popt2Config? = runCatching { parse(cfg) }.getOrNull()

        private fun parse(cfg: JsonObject): Popt2Config? {
            fun int(k: String) = (cfg[k] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull
            val versions = (cfg["popt_versions"] as? JsonArray)?.map { it.jsonPrimitive.int } ?: return null
            if (2 !in versions) return null
            val t0 = (cfg["t0_v2"] as? JsonPrimitive)?.doubleOrNull
            if (int("delta_ms") != DELTA_MS || t0 != Popt2Rule.T0 || int("fir_taps") != Popt2Rule.TAPS ||
                int("template_bits") != TEMPLATE_BITS || int("leaf") != RecTree.LEAF || int("tree_depth") != RecTree.DEPTH
            ) return null
            val tol = int("self_os_tol_ms") ?: return null
            val table = cfg["popt2_rates"] as? JsonObject ?: return null
            val rates = HashMap<Int, Popt2Rate>()
            for ((k, v) in table) {
                val sr = k.toIntOrNull() ?: continue
                val o = v.jsonObject
                fun n(f: String) = o[f]!!.jsonPrimitive.longOrNull!!
                val r = Popt2Rate(sr, n("L").toInt(), n("B"), n("delta").toInt(), n("wpre").toInt(), n("wpost").toInt(),
                    o["h"]!!.jsonArray.map { it.jsonPrimitive.int }.toIntArray())
                // only rates the app also knows, with the same numbers (h and B are not re-derivable here)
                if (Popt2Rates.builtIn[sr]?.sameAs(r) == true && r.delta == DELTA_MS * sr / 1000) rates[sr] = r
            }
            return if (rates.isEmpty()) null else Popt2Config(rates, tol)
        }
    }
}
