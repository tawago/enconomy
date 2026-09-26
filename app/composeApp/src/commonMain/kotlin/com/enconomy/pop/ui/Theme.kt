package com.enconomy.pop.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Colors Material has no slot for: verdict tones and the signal accent used by the sound visuals. */
@Immutable
data class PopPalette(
    val dark: Boolean,
    val signal: Color,
    val signalSoft: Color,
    val good: Color,
    val goodSoft: Color,
    val warn: Color,
    val warnSoft: Color,
    val bad: Color,
    val badSoft: Color,
    val muted: Color,
    val hairline: Color,
    val panel: Color,
    val panelRaised: Color,
    val code: Color,
)

private val DarkPalette = PopPalette(
    dark = true,
    signal = Color(0xFF4BE3AC),
    signalSoft = Color(0x264BE3AC),
    good = Color(0xFF4BE3AC),
    goodSoft = Color(0x1F4BE3AC),
    warn = Color(0xFFFFB547),
    warnSoft = Color(0x1FFFB547),
    bad = Color(0xFFFF6166),
    badSoft = Color(0x1FFF6166),
    muted = Color(0xFF8A93A3),
    hairline = Color(0xFF232933),
    panel = Color(0xFF12161D),
    panelRaised = Color(0xFF1A1F28),
    code = Color(0xFF0D1015),
)

private val LightPalette = PopPalette(
    dark = false,
    signal = Color(0xFF0B9E6F),
    signalSoft = Color(0x1F0B9E6F),
    good = Color(0xFF0B9E6F),
    goodSoft = Color(0x170B9E6F),
    warn = Color(0xFFB86E00),
    warnSoft = Color(0x1AE08A00),
    bad = Color(0xFFD7263D),
    badSoft = Color(0x14D7263D),
    muted = Color(0xFF5E6776),
    hairline = Color(0xFFE2E5EA),
    panel = Color(0xFFFFFFFF),
    panelRaised = Color(0xFFF1F3F6),
    code = Color(0xFFF1F3F6),
)

private fun scheme(p: PopPalette): ColorScheme = if (p.dark) darkColorScheme(
    primary = p.signal,
    onPrimary = Color(0xFF03140D),
    primaryContainer = Color(0xFF123A2C),
    onPrimaryContainer = Color(0xFFB9F8DF),
    secondary = Color(0xFFB7C0CF),
    onSecondary = Color(0xFF0A0C10),
    secondaryContainer = p.panelRaised,
    onSecondaryContainer = Color(0xFFEEF1F5),
    background = Color(0xFF0A0C10),
    onBackground = Color(0xFFEEF1F5),
    surface = Color(0xFF0A0C10),
    onSurface = Color(0xFFEEF1F5),
    surfaceVariant = p.panelRaised,
    onSurfaceVariant = p.muted,
    surfaceContainerLowest = Color(0xFF07090C),
    surfaceContainerLow = Color(0xFF0F1318),
    surfaceContainer = p.panel,
    surfaceContainerHigh = p.panelRaised,
    surfaceContainerHighest = Color(0xFF222833),
    outline = Color(0xFF3A4250),
    outlineVariant = p.hairline,
    error = p.bad,
    onError = Color(0xFF1A0406),
) else lightColorScheme(
    primary = p.signal,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD5F5E8),
    onPrimaryContainer = Color(0xFF00301F),
    secondary = Color(0xFF3B4250),
    onSecondary = Color.White,
    secondaryContainer = p.panelRaised,
    onSecondaryContainer = Color(0xFF0D1117),
    background = Color(0xFFF5F6F8),
    onBackground = Color(0xFF0D1117),
    surface = Color(0xFFF5F6F8),
    onSurface = Color(0xFF0D1117),
    surfaceVariant = p.panelRaised,
    onSurfaceVariant = p.muted,
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFFAFBFC),
    surfaceContainer = p.panel,
    surfaceContainerHigh = p.panelRaised,
    surfaceContainerHighest = Color(0xFFE7EAEE),
    outline = Color(0xFFC3C8D0),
    outlineVariant = p.hairline,
    error = p.bad,
    onError = Color.White,
)

private val base = Typography()

private val PopTypography = Typography(
    displayLarge = base.displayLarge.copy(fontWeight = FontWeight.Bold, fontSize = 54.sp, lineHeight = 58.sp, letterSpacing = (-1.8).sp),
    displayMedium = base.displayMedium.copy(fontWeight = FontWeight.Bold, fontSize = 40.sp, lineHeight = 44.sp, letterSpacing = (-1.2).sp),
    headlineLarge = base.headlineLarge.copy(fontWeight = FontWeight.Bold, fontSize = 32.sp, lineHeight = 38.sp, letterSpacing = (-0.8).sp),
    headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.Bold, fontSize = 28.sp, lineHeight = 34.sp, letterSpacing = (-0.6).sp),
    headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 28.sp, letterSpacing = (-0.3).sp),
    titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp, letterSpacing = (-0.2).sp),
    titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 22.sp, letterSpacing = 0.sp),
    titleSmall = base.titleSmall.copy(fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp, letterSpacing = 0.sp),
    bodyLarge = base.bodyLarge.copy(fontSize = 16.sp, lineHeight = 24.sp, letterSpacing = 0.sp),
    bodyMedium = base.bodyMedium.copy(fontSize = 14.sp, lineHeight = 21.sp, letterSpacing = 0.sp),
    bodySmall = base.bodySmall.copy(fontSize = 12.5.sp, lineHeight = 18.sp, letterSpacing = 0.sp),
    labelLarge = base.labelLarge.copy(fontWeight = FontWeight.SemiBold, fontSize = 15.sp, letterSpacing = 0.sp),
    labelMedium = base.labelMedium.copy(fontWeight = FontWeight.SemiBold, fontSize = 12.sp, letterSpacing = 0.2.sp),
    labelSmall = base.labelSmall.copy(fontWeight = FontWeight.SemiBold, fontSize = 10.5.sp, letterSpacing = 1.1.sp),
)

private val PopShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

val LocalPopPalette = staticCompositionLocalOf { DarkPalette }

object Pop {
    val palette: PopPalette
        @Composable @ReadOnlyComposable get() = LocalPopPalette.current

    /** Monospace for ids, hex and measurement tables. */
    val mono: TextStyle
        @Composable @ReadOnlyComposable get() = MaterialTheme.typography.bodySmall.copy(
            fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 17.sp,
        )
}

@Composable
fun PopTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val p = if (dark) DarkPalette else LightPalette
    CompositionLocalProvider(LocalPopPalette provides p) {
        MaterialTheme(colorScheme = scheme(p), typography = PopTypography, shapes = PopShapes, content = content)
    }
}
