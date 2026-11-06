package com.enconomy.pop.ui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathBuilder
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

/** Stroke icons on a 24 grid (no icon dependency); tinted by Icon(). */
object PopIcons {
    private fun icon(name: String, block: PathBuilder.() -> Unit): ImageVector =
        ImageVector.Builder(name, 24.dp, 24.dp, 24f, 24f).path(
            stroke = SolidColor(Color.Black),
            strokeLineWidth = 1.9f,
            strokeLineCap = StrokeCap.Round,
            strokeLineJoin = StrokeJoin.Round,
            pathBuilder = block,
        ).build()

    private fun PathBuilder.circle(cx: Float, cy: Float, r: Float) {
        moveTo(cx - r, cy)
        arcToRelative(r, r, 0f, true, true, 2 * r, 0f)
        arcToRelative(r, r, 0f, true, true, -2 * r, 0f)
        close()
    }

    private fun PathBuilder.rect(x: Float, y: Float, w: Float, h: Float) {
        moveTo(x, y); lineTo(x + w, y); lineTo(x + w, y + h); lineTo(x, y + h); close()
    }

    val Back = icon("back") { moveTo(15f, 5f); lineTo(8f, 12f); lineTo(15f, 19f) }
    val Check = icon("check") { moveTo(5f, 12.5f); lineTo(10f, 17.5f); lineTo(19f, 7f) }
    val Close = icon("close") { moveTo(6f, 6f); lineTo(18f, 18f); moveTo(18f, 6f); lineTo(6f, 18f) }
    val ChevronDown = icon("chevronDown") { moveTo(6f, 9f); lineTo(12f, 15f); lineTo(18f, 9f) }
    val ChevronRight = icon("chevronRight") { moveTo(9f, 6f); lineTo(15f, 12f); lineTo(9f, 18f) }

    val Qr = icon("qr") {
        rect(4f, 4f, 6f, 6f); rect(14f, 4f, 6f, 6f); rect(4f, 14f, 6f, 6f)
        moveTo(14f, 14f); lineTo(14f, 16f); moveTo(17f, 14f); lineTo(20f, 14f)
        moveTo(20f, 17f); lineTo(20f, 20f); lineTo(17f, 20f); moveTo(14f, 19f); lineTo(14f, 20f)
    }

    val Scan = icon("scan") {
        moveTo(4f, 9f); lineTo(4f, 6f); quadTo(4f, 4f, 6f, 4f); lineTo(9f, 4f)
        moveTo(15f, 4f); lineTo(18f, 4f); quadTo(20f, 4f, 20f, 6f); lineTo(20f, 9f)
        moveTo(20f, 15f); lineTo(20f, 18f); quadTo(20f, 20f, 18f, 20f); lineTo(15f, 20f)
        moveTo(9f, 20f); lineTo(6f, 20f); quadTo(4f, 20f, 4f, 18f); lineTo(4f, 15f)
        moveTo(7f, 12f); lineTo(17f, 12f)
    }

    /** Contactless waves. */
    val Nfc = icon("nfc") {
        moveTo(7f, 8.5f); quadTo(8.6f, 12f, 7f, 15.5f)
        moveTo(10.5f, 6f); quadTo(13.4f, 12f, 10.5f, 18f)
        moveTo(14f, 3.5f); quadTo(18.2f, 12f, 14f, 20.5f)
    }

    val Speaker = icon("speaker") {
        moveTo(4f, 9.5f); lineTo(7.5f, 9.5f); lineTo(12f, 5.5f); lineTo(12f, 18.5f); lineTo(7.5f, 14.5f); lineTo(4f, 14.5f); close()
        moveTo(15.5f, 9f); quadTo(17.2f, 12f, 15.5f, 15f)
        moveTo(18f, 6.5f); quadTo(21.4f, 12f, 18f, 17.5f)
    }

    val Chip = icon("chip") {
        rect(7f, 7f, 10f, 10f)
        rect(10f, 10f, 4f, 4f)
        moveTo(10f, 4f); lineTo(10f, 7f); moveTo(14f, 4f); lineTo(14f, 7f)
        moveTo(10f, 17f); lineTo(10f, 20f); moveTo(14f, 17f); lineTo(14f, 20f)
        moveTo(4f, 10f); lineTo(7f, 10f); moveTo(4f, 14f); lineTo(7f, 14f)
        moveTo(17f, 10f); lineTo(20f, 10f); moveTo(17f, 14f); lineTo(20f, 14f)
    }

    val Server = icon("server") {
        moveTo(5f, 4.5f); lineTo(19f, 4.5f); quadTo(20f, 4.5f, 20f, 5.5f); lineTo(20f, 9.5f); quadTo(20f, 10.5f, 19f, 10.5f)
        lineTo(5f, 10.5f); quadTo(4f, 10.5f, 4f, 9.5f); lineTo(4f, 5.5f); quadTo(4f, 4.5f, 5f, 4.5f); close()
        moveTo(5f, 13.5f); lineTo(19f, 13.5f); quadTo(20f, 13.5f, 20f, 14.5f); lineTo(20f, 18.5f); quadTo(20f, 19.5f, 19f, 19.5f)
        lineTo(5f, 19.5f); quadTo(4f, 19.5f, 4f, 18.5f); lineTo(4f, 14.5f); quadTo(4f, 13.5f, 5f, 13.5f); close()
        moveTo(7.5f, 7.5f); lineTo(8f, 7.5f); moveTo(7.5f, 16.5f); lineTo(8f, 16.5f)
    }

    val Shield = icon("shield") {
        moveTo(12f, 3.5f); lineTo(19f, 6f); lineTo(19f, 11.5f); quadTo(19f, 17.5f, 12f, 20.5f)
        quadTo(5f, 17.5f, 5f, 11.5f); lineTo(5f, 6f); close()
        moveTo(9f, 12f); lineTo(11.2f, 14.2f); lineTo(15.2f, 9.8f)
    }

    val Key = icon("key") {
        circle(8f, 12f, 3.5f)
        moveTo(11.5f, 12f); lineTo(20f, 12f); moveTo(17f, 12f); lineTo(17f, 15f); moveTo(20f, 12f); lineTo(20f, 14.5f)
    }

    val Refresh = icon("refresh") {
        moveTo(19f, 12f); arcTo(7f, 7f, 0f, true, true, 16.9f, 7f)
        moveTo(17.5f, 3.5f); lineTo(17.5f, 7.5f); lineTo(13.5f, 7.5f)
    }

    val Mic = icon("mic") {
        moveTo(9f, 6.5f); arcTo(3f, 3f, 0f, false, true, 15f, 6.5f); lineTo(15f, 11.5f)
        arcTo(3f, 3f, 0f, false, true, 9f, 11.5f); close()
        moveTo(6f, 11f); arcTo(6f, 6f, 0f, false, false, 18f, 11f)
        moveTo(12f, 17f); lineTo(12f, 20.5f)
    }

    val Volume = icon("volume") {
        moveTo(4f, 9.5f); lineTo(7.5f, 9.5f); lineTo(12f, 5.5f); lineTo(12f, 18.5f); lineTo(7.5f, 14.5f); lineTo(4f, 14.5f); close()
        moveTo(16f, 12f); lineTo(21f, 12f); moveTo(18.5f, 9.5f); lineTo(18.5f, 14.5f)
    }

    val Alert = icon("alert") {
        moveTo(12f, 4f); lineTo(21f, 19.5f); lineTo(3f, 19.5f); close()
        moveTo(12f, 10f); lineTo(12f, 14f); moveTo(12f, 16.8f); lineTo(12f, 17f)
    }

    val Info = icon("info") {
        circle(12f, 12f, 8.5f)
        moveTo(12f, 11f); lineTo(12f, 16f); moveTo(12f, 8f); lineTo(12f, 8.2f)
    }

    val Logout = icon("reset") {
        moveTo(14f, 4.5f); lineTo(18f, 4.5f); quadTo(19.5f, 4.5f, 19.5f, 6f); lineTo(19.5f, 18f); quadTo(19.5f, 19.5f, 18f, 19.5f); lineTo(14f, 19.5f)
        moveTo(10f, 8f); lineTo(6f, 12f); lineTo(10f, 16f); moveTo(6f, 12f); lineTo(15f, 12f)
    }

    val Wave = icon("wave") {
        moveTo(3f, 12f); lineTo(5f, 12f); moveTo(7f, 9f); lineTo(7f, 15f); moveTo(10f, 5f); lineTo(10f, 19f)
        moveTo(13f, 8f); lineTo(13f, 16f); moveTo(16f, 10f); lineTo(16f, 14f); moveTo(19f, 11.5f); lineTo(19f, 12.5f)
    }
}
