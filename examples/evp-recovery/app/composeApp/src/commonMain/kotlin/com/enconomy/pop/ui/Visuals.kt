package com.enconomy.pop.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.max
import kotlin.math.min

/** Brand mark: a dot with two sound arcs each side, "((•))". */
@Composable
fun PopMark(size: Dp, color: Color = Pop.palette.signal, modifier: Modifier = Modifier) {
    Canvas(modifier.size(size)) { drawMark(color, center, this.size.minDimension) }
}

private fun DrawScope.drawMark(color: Color, c: Offset, d: Float, arcAlpha: Float = 1f) {
    val w = d * 0.075f
    drawCircle(color, d * 0.12f, c)
    for ((i, r) in listOf(0.29f, 0.45f).withIndex()) {
        val rr = d * r
        val a = if (i == 0) arcAlpha else arcAlpha * 0.55f
        for (start in listOf(-40f, 140f)) {
            drawArc(color.copy(alpha = color.alpha * a), start, 80f, false, Offset(c.x - rr, c.y - rr), Size(rr * 2, rr * 2),
                style = Stroke(w, cap = StrokeCap.Round))
        }
    }
}

/** Rings expanding out from the center, for "listening / waiting" moments. */
@Composable
fun PulseRings(modifier: Modifier, color: Color = Pop.palette.signal, rings: Int = 3, periodMs: Int = 2400, startFrac: Float = 0.18f) {
    val t = rememberInfiniteTransition(label = "pulse")
    val p by t.animateFloat(0f, 1f, infiniteRepeatable(tween(periodMs, easing = LinearEasing)), label = "p")
    Canvas(modifier) {
        val rMax = size.minDimension / 2
        for (i in 0 until rings) {
            val f = (p + i.toFloat() / rings) % 1f
            val r = rMax * (startFrac + (1 - startFrac) * FastOutSlowInEasing.transform(f))
            val a = (1 - f) * (1 - f)
            drawCircle(color.copy(alpha = 0.10f * a), r, center)
            drawCircle(color.copy(alpha = 0.55f * a), r, center, style = Stroke(1.5.dp.toPx()))
        }
    }
}

/** Two phones side by side with sound travelling between them. [active] animates the waves. */
@Composable
fun PhonesDuo(modifier: Modifier, active: Boolean = true) {
    val pal = Pop.palette
    val body = MaterialTheme.colorScheme.surfaceContainerHighest
    val edge = MaterialTheme.colorScheme.outline
    val t = rememberInfiniteTransition(label = "duo")
    val p by t.animateFloat(0f, 1f, infiniteRepeatable(tween(1800, easing = LinearEasing)), label = "p")
    val breathe by t.animateFloat(0.6f, 1f, infiniteRepeatable(tween(1400, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "b")
    Canvas(modifier) {
        val h = size.height * 0.86f
        val w = h * 0.5f
        val gap = min(size.width - 2 * w, h * 0.9f)
        val left = Offset(center.x - gap / 2 - w, center.y - h / 2)
        val right = Offset(center.x + gap / 2, center.y - h / 2)
        val cr = CornerRadius(w * 0.2f)
        for ((i, o) in listOf(left, right).withIndex()) {
            drawRoundRect(body, o, Size(w, h), cr)
            drawRoundRect(edge.copy(alpha = 0.6f), o, Size(w, h), cr, style = Stroke(1.dp.toPx()))
            // screen glow
            val inset = w * 0.09f
            drawRoundRect(
                Brush.verticalGradient(listOf(pal.signal.copy(alpha = 0.22f), pal.signal.copy(alpha = 0.04f)), o.y, o.y + h),
                Offset(o.x + inset, o.y + inset), Size(w - 2 * inset, h - 2 * inset), CornerRadius(w * 0.13f),
            )
            drawMark(pal.signal.copy(alpha = if (active) breathe else 0.7f), Offset(o.x + w / 2, o.y + h * 0.45f), w * 0.55f,
                arcAlpha = if (i == 0) 1f else 0.8f)
            drawRoundRect(edge.copy(alpha = 0.5f), Offset(o.x + w * 0.38f, o.y + h - inset * 1.4f), Size(w * 0.24f, 2.dp.toPx()), CornerRadius(2f))
        }
        // waves crossing the gap in both directions
        val cy = center.y
        val span = gap - 8.dp.toPx()
        if (span > 0) {
            for (k in 0 until 3) {
                val f = if (active) (p + k / 3f) % 1f else (k + 1) / 4f
                val a = (if (active) (1 - f) * min(1f, f * 4) else 0.5f)
                val r = h * 0.12f + span * 0.9f * f
                drawArc(pal.signal.copy(alpha = a * 0.9f), -32f, 64f, false, Offset(left.x + w - r + 4.dp.toPx(), cy - r), Size(2 * r, 2 * r),
                    style = Stroke(2.dp.toPx(), cap = StrokeCap.Round))
                val f2 = if (active) (p + k / 3f + 0.5f) % 1f else (k + 1) / 4f
                val a2 = (if (active) (1 - f2) * min(1f, f2 * 4) else 0.5f)
                val r2 = h * 0.12f + span * 0.9f * f2
                drawArc(pal.signal.copy(alpha = a2 * 0.6f), 148f, 64f, false, Offset(right.x + r2 - 4.dp.toPx() - 2 * r2, cy - r2), Size(2 * r2, 2 * r2),
                    style = Stroke(2.dp.toPx(), cap = StrokeCap.Round))
            }
        }
    }
}

/** Animated verdict disc: pops in, then draws a check or a cross, with a halo burst. */
@Composable
fun VerdictBadge(good: Boolean, modifier: Modifier = Modifier, size: Dp = 132.dp) {
    val pal = Pop.palette
    val color = if (good) pal.good else pal.bad
    val scale = remember { Animatable(0.4f) }
    val draw = remember { Animatable(0f) }
    val halo = remember { Animatable(0f) }
    LaunchedEffect(good) {
        scale.snapTo(0.4f); draw.snapTo(0f); halo.snapTo(0f)
        scale.animateTo(1f, spring(dampingRatio = 0.5f, stiffness = Spring.StiffnessLow))
    }
    LaunchedEffect(good) { kotlinx.coroutines.delay(180); draw.animateTo(1f, tween(520, easing = FastOutSlowInEasing)) }
    LaunchedEffect(good) { kotlinx.coroutines.delay(120); halo.animateTo(1f, tween(1100, easing = FastOutSlowInEasing)) }
    val strokes = remember { List(2) { Path() } }
    val seg = remember { Path() }
    val pm = remember { PathMeasure() }
    Canvas(modifier.size(size * 1.5f)) {
        val c = center
        val r = size.toPx() / 2 * 0.78f
        val h = halo.value
        if (h in 0.001f..0.999f) {
            drawCircle(color.copy(alpha = 0.35f * (1 - h)), r * (1f + 0.5f * h), c, style = Stroke(2.dp.toPx()))
            drawCircle(color.copy(alpha = 0.18f * (1 - h)), r * (1f + 0.9f * h), c, style = Stroke(1.dp.toPx()))
        }
        drawCircle(color.copy(alpha = 0.10f), r * 1.22f * scale.value, c)
        drawCircle(color, r * scale.value, c)
        val u = r / 10
        strokes.forEach { it.reset() }
        if (good) {
            strokes[0].apply { moveTo(c.x - 4.2f * u, c.y + 0.2f * u); lineTo(c.x - 1.2f * u, c.y + 3.2f * u); lineTo(c.x + 4.4f * u, c.y - 3.2f * u) }
        } else {
            strokes[0].apply { moveTo(c.x - 3.3f * u, c.y - 3.3f * u); lineTo(c.x + 3.3f * u, c.y + 3.3f * u) }
            strokes[1].apply { moveTo(c.x + 3.3f * u, c.y - 3.3f * u); lineTo(c.x - 3.3f * u, c.y + 3.3f * u) }
        }
        seg.reset()
        val n = if (good) 1 else 2
        for (i in 0 until n) {
            val f = ((draw.value * n) - i).coerceIn(0f, 1f)
            if (f <= 0f) continue
            pm.setPath(strokes[i], false)
            pm.getSegment(0f, pm.length * f, seg, true)
        }
        drawPath(seg, if (pal.dark) Color(0xFF06110C) else Color.White, style = Stroke(1.4f * u, cap = StrokeCap.Round))
    }
}

/**
 * Distance bar 0..scale with the near zone shaded; the marker glides to [cm].
 */
@Composable
fun DistanceMeter(cm: Double, nearCm: Int, modifier: Modifier = Modifier) {
    val pal = Pop.palette
    val near = cm <= nearCm
    val scaleMax = max(nearCm * 2.0, cm * 1.15).toFloat()
    val anim = remember { Animatable(0f) }
    LaunchedEffect(cm) { anim.animateTo(cm.toFloat().coerceAtLeast(0f), tween(1100, 250, FastOutSlowInEasing)) }
    val track = MaterialTheme.colorScheme.surfaceContainerHighest
    val tone = if (near) pal.good else pal.bad
    Column(modifier) {
        Canvas(Modifier.fillMaxWidth().height(34.dp)) {
            val th = 10.dp.toPx()
            val y = size.height - th - 4.dp.toPx()
            val cr = CornerRadius(th / 2)
            drawRoundRect(track, Offset(0f, y), Size(size.width, th), cr)
            val nz = size.width * (nearCm / scaleMax)
            drawRoundRect(pal.good.copy(alpha = 0.28f), Offset(0f, y), Size(nz, th), cr)
            // limit tick
            drawLine(pal.good, Offset(nz, y - 5.dp.toPx()), Offset(nz, y + th + 3.dp.toPx()), 2.dp.toPx(), StrokeCap.Round)
            // marker
            val x = (size.width * (anim.value / scaleMax)).coerceIn(th / 2, size.width - th / 2)
            drawRoundRect(tone, Offset(0f, y), Size(x, th), cr)
            drawCircle(tone.copy(alpha = 0.25f), th * 1.3f, Offset(x, y + th / 2))
            drawCircle(tone, th * 0.8f, Offset(x, y + th / 2))
            drawCircle(Color.White, th * 0.32f, Offset(x, y + th / 2))
        }
        val frac = (nearCm / scaleMax).coerceIn(0f, 1f)
        Layout(content = {
            Text("0", style = MaterialTheme.typography.labelMedium, color = pal.muted)
            Text("$nearCm cm limit", style = MaterialTheme.typography.labelMedium, color = pal.good)
        }, modifier = Modifier.fillMaxWidth()) { ms, cs ->
            val loose = cs.copy(minWidth = 0)
            val zero = ms[0].measure(loose)
            val lim = ms[1].measure(loose)
            val w = cs.maxWidth
            layout(w, max(zero.height, lim.height)) {
                zero.place(0, 0)
                val x = (w * frac - lim.width / 2f).toInt().coerceIn(zero.width + 8, (w - lim.width).coerceAtLeast(0))
                lim.place(x, 0)
            }
        }
    }
}

/** Horizontal level bar: [value] dB against [ok] threshold on a 0..[full] dB scale. */
@Composable
fun MarginBar(label: String, value: Double, ok: Double, weak: Double, full: Double = 60.0, modifier: Modifier = Modifier) {
    val pal = Pop.palette
    val tone = when {
        value >= ok -> pal.good
        value >= weak -> pal.warn
        else -> pal.bad
    }
    val anim = remember { Animatable(0f) }
    LaunchedEffect(value) { anim.animateTo((value / full).toFloat().coerceIn(0f, 1f), tween(900, easing = FastOutSlowInEasing)) }
    val track = MaterialTheme.colorScheme.surfaceContainerHighest
    Column(modifier) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = pal.muted, modifier = Modifier.weight(1f))
            Text("${fmt1(value)} dB", style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.Bold), color = tone)
        }
        Spacer(Modifier.height(6.dp))
        Canvas(Modifier.fillMaxWidth().height(8.dp)) {
            val cr = CornerRadius(size.height / 2)
            drawRoundRect(track, size = size, cornerRadius = cr)
            drawRoundRect(tone, size = Size(size.width * anim.value, size.height), cornerRadius = cr)
            val okX = size.width * (ok / full).toFloat().coerceIn(0f, 1f)
            drawLine(pal.muted, Offset(okX, -2.dp.toPx()), Offset(okX, size.height + 2.dp.toPx()), 1.5.dp.toPx())
        }
    }
}

fun fmt1(x: Double): String {
    val r = kotlin.math.round(x * 10) / 10
    return if (r == kotlin.math.floor(r) && kotlin.math.abs(r) < 1e15) "${r.toLong()}.0" else r.toString()
}
