package com.enconomy.pop.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

enum class Tone { Neutral, Accent, Good, Warn, Bad }

@Composable
fun toneColor(t: Tone): Color = when (t) {
    Tone.Neutral -> Pop.palette.muted
    Tone.Accent -> Pop.palette.signal
    Tone.Good -> Pop.palette.good
    Tone.Warn -> Pop.palette.warn
    Tone.Bad -> Pop.palette.bad
}

@Composable
fun toneSoft(t: Tone): Color = when (t) {
    Tone.Neutral -> MaterialTheme.colorScheme.surfaceContainerHigh
    Tone.Accent -> Pop.palette.signalSoft
    Tone.Good -> Pop.palette.goodSoft
    Tone.Warn -> Pop.palette.warnSoft
    Tone.Bad -> Pop.palette.badSoft
}

/** Rounded content panel with a hairline border. */
@Composable
fun Panel(
    modifier: Modifier = Modifier,
    padding: PaddingValues = PaddingValues(18.dp),
    spacing: Dp = 12.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.large,
        color = Pop.palette.panel,
        border = BorderStroke(1.dp, Pop.palette.hairline),
    ) {
        Column(Modifier.padding(padding), verticalArrangement = Arrangement.spacedBy(spacing), content = content)
    }
}

/** Fades and lifts its content in once, when first shown. [delayMs] staggers siblings. */
@Composable
fun Reveal(delayMs: Int = 0, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val a = remember { Animatable(0f) }
    LaunchedEffect(Unit) { a.animateTo(1f, tween(420, delayMs, FastOutSlowInEasing)) }
    Box(modifier.graphicsLayer { alpha = a.value; translationY = (1 - a.value) * 14.dp.toPx() }) { content() }
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(), style = MaterialTheme.typography.labelSmall, color = Pop.palette.muted,
        modifier = modifier.padding(start = 4.dp, top = 6.dp),
    )
}

@Composable
fun PrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
    icon: ImageVector? = null,
    tone: Tone = Tone.Accent,
) {
    val bg = toneColor(tone)
    Button(
        onClick = onClick,
        enabled = enabled && !loading,
        modifier = modifier.heightIn(min = 56.dp),
        shape = MaterialTheme.shapes.medium,
        colors = ButtonDefaults.buttonColors(
            containerColor = bg,
            contentColor = MaterialTheme.colorScheme.onPrimary,
            disabledContainerColor = if (loading) bg.copy(alpha = 0.55f) else MaterialTheme.colorScheme.surfaceContainerHighest,
            disabledContentColor = if (loading) MaterialTheme.colorScheme.onPrimary else Pop.palette.muted,
        ),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 14.dp),
    ) {
        ButtonContent(text, icon, loading, MaterialTheme.colorScheme.onPrimary)
    }
}

@Composable
fun SecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
    icon: ImageVector? = null,
    compact: Boolean = false,
) {
    Button(
        onClick = onClick,
        enabled = enabled && !loading,
        modifier = modifier.heightIn(min = if (compact) 40.dp else 52.dp),
        shape = MaterialTheme.shapes.medium,
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
            contentColor = MaterialTheme.colorScheme.onSurface,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh.copy(alpha = 0.5f),
            disabledContentColor = Pop.palette.muted.copy(alpha = 0.6f),
        ),
        border = BorderStroke(1.dp, Pop.palette.hairline),
        contentPadding = if (compact) PaddingValues(horizontal = 14.dp, vertical = 8.dp) else PaddingValues(horizontal = 18.dp, vertical = 12.dp),
    ) {
        ButtonContent(text, icon, loading, MaterialTheme.colorScheme.onSurface)
    }
}

@Composable
fun QuietButton(text: String, onClick: () -> Unit, enabled: Boolean = true, tone: Tone = Tone.Accent, modifier: Modifier = Modifier) {
    TextButton(onClick = onClick, enabled = enabled, modifier = modifier, shape = MaterialTheme.shapes.small) {
        Text(text, style = MaterialTheme.typography.labelLarge, color = if (enabled) toneColor(tone) else Pop.palette.muted.copy(alpha = 0.5f))
    }
}

@Composable
private fun RowScope.ButtonContent(text: String, icon: ImageVector?, loading: Boolean, color: Color) {
    if (loading) {
        CircularProgressIndicator(Modifier.size(18.dp), color = color, strokeWidth = 2.dp)
        Spacer(Modifier.width(10.dp))
    } else if (icon != null) {
        Icon(icon, null, Modifier.size(20.dp))
        Spacer(Modifier.width(10.dp))
    }
    Text(text, style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
}

/** Small rounded status tag. */
@Composable
fun Pill(text: String, tone: Tone = Tone.Neutral, dot: Boolean = false, icon: ImageVector? = null, modifier: Modifier = Modifier) {
    val c = toneColor(tone)
    Row(
        modifier.clip(CircleShape).background(toneSoft(tone)).padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (dot) {
            Box(Modifier.size(7.dp).clip(CircleShape).background(c))
            Spacer(Modifier.width(6.dp))
        }
        if (icon != null) {
            Icon(icon, null, Modifier.size(13.dp), tint = c)
            Spacer(Modifier.width(5.dp))
        }
        Text(text, style = MaterialTheme.typography.labelMedium, color = if (tone == Tone.Neutral) MaterialTheme.colorScheme.onSurface else c, maxLines = 1)
    }
}

/** Inline message strip. */
@Composable
fun Banner(text: String, tone: Tone, title: String? = null, modifier: Modifier = Modifier, actions: (@Composable RowScope.() -> Unit)? = null) {
    val c = toneColor(tone)
    Row(
        modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).background(toneSoft(tone))
            .border(1.dp, c.copy(alpha = 0.25f), MaterialTheme.shapes.medium).padding(14.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Icon(if (tone == Tone.Bad || tone == Tone.Warn) PopIcons.Alert else PopIcons.Info, null, Modifier.size(20.dp), tint = c)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (title != null) Text(title, style = MaterialTheme.typography.titleSmall, color = c)
            SelectionContainer { Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface) }
            if (actions != null) {
                Spacer(Modifier.size(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), content = actions)
            }
        }
    }
}

/** Label over value; mono values are selectable (ids, hex). */
@Composable
fun Field(label: String, value: String, mono: Boolean = true, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = Pop.palette.muted)
        SelectionContainer {
            Text(value, style = if (mono) Pop.mono else MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface)
        }
    }
}

/** Label left, value right, single line. */
@Composable
fun FactRow(label: String, value: String, valueTone: Tone? = null, mono: Boolean = false) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = Pop.palette.muted, modifier = Modifier.padding(end = 12.dp))
        Spacer(Modifier.weight(1f))
        Text(
            value, style = if (mono) Pop.mono else MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
            color = valueTone?.let { toneColor(it) } ?: MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.End, maxLines = 2, overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
fun CodeBlock(text: String, modifier: Modifier = Modifier) {
    Box(
        modifier.fillMaxWidth().clip(MaterialTheme.shapes.small).background(Pop.palette.code)
            .border(1.dp, Pop.palette.hairline, MaterialTheme.shapes.small).padding(12.dp),
    ) {
        SelectionContainer { Text(text, style = Pop.mono.copy(fontSize = MaterialTheme.typography.labelSmall.fontSize * 1.05f), color = MaterialTheme.colorScheme.onSurface) }
    }
}

/** One-of-N selector. */
@Composable
fun Segmented(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit, enabled: Boolean = true) {
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).background(MaterialTheme.colorScheme.surfaceContainerHigh)
            .border(1.dp, Pop.palette.hairline, MaterialTheme.shapes.medium).padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        for ((key, label) in options) {
            val on = key == selected
            val bg by animateColorAsState(if (on) MaterialTheme.colorScheme.primary else Color.Transparent, tween(220), label = "seg")
            val fg by animateColorAsState(
                when {
                    on -> MaterialTheme.colorScheme.onPrimary
                    enabled -> MaterialTheme.colorScheme.onSurface
                    else -> Pop.palette.muted.copy(alpha = 0.5f)
                }, tween(220), label = "segfg",
            )
            Box(
                Modifier.weight(1f).heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp)).background(bg)
                    .clickable(enabled = enabled && !on) { onSelect(key) },
                contentAlignment = Alignment.Center,
            ) {
                Text(label, style = MaterialTheme.typography.labelLarge, color = fg, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(horizontal = 6.dp))
            }
        }
    }
}

@Composable
fun SwitchRow(title: String, subtitle: String?, checked: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true, icon: ImageVector? = null) {
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable(enabled = enabled) { onChange(!checked) }.padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            IconTile(icon)
            Spacer(Modifier.width(14.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted)
        }
        Spacer(Modifier.width(12.dp))
        Switch(
            checked = checked, onCheckedChange = onChange, enabled = enabled,
            colors = SwitchDefaults.colors(
                checkedTrackColor = MaterialTheme.colorScheme.primary,
                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                uncheckedTrackColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                uncheckedBorderColor = MaterialTheme.colorScheme.outline,
                uncheckedThumbColor = Pop.palette.muted,
            ),
        )
    }
}

@Composable
fun IconTile(icon: ImageVector, tone: Tone = Tone.Accent, size: Dp = 38.dp) {
    Box(
        Modifier.size(size).clip(RoundedCornerShape(size * 0.3f)).background(toneSoft(tone)),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, null, Modifier.size(size * 0.52f), tint = toneColor(tone)) }
}

/** Tappable list row with icon tile, title, subtitle and chevron. */
@Composable
fun NavRow(icon: ImageVector, title: String, subtitle: String?, onClick: () -> Unit, enabled: Boolean = true, tone: Tone = Tone.Accent) {
    Row(
        Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable(enabled = enabled, onClick = onClick)
            .graphicsLayer { alpha = if (enabled) 1f else 0.45f }.padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconTile(icon, tone)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = if (tone == Tone.Bad) Pop.palette.bad else MaterialTheme.colorScheme.onSurface)
            if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Icon(PopIcons.ChevronRight, null, Modifier.size(18.dp), tint = Pop.palette.muted)
    }
}

/** Header row that reveals its body. */
@Composable
fun Expandable(
    title: String,
    subtitle: String? = null,
    icon: ImageVector? = null,
    initiallyOpen: Boolean = false,
    content: @Composable ColumnScope.() -> Unit,
) {
    var open by rememberSaveable(title) { mutableStateOf(initiallyOpen) }
    val rot by animateFloatAsState(if (open) 180f else 0f, tween(250), label = "chev")
    Column {
        Row(
            Modifier.fillMaxWidth().clip(MaterialTheme.shapes.medium).clickable { open = !open }.padding(vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                IconTile(icon, Tone.Neutral)
                Spacer(Modifier.width(14.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleSmall)
                if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Pop.palette.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Icon(PopIcons.ChevronDown, null, Modifier.size(20.dp).rotate(rot), tint = Pop.palette.muted)
        }
        AnimatedVisibility(open, enter = expandVertically(tween(260)) + fadeIn(tween(260)), exit = shrinkVertically(tween(220)) + fadeOut(tween(160))) {
            Column(Modifier.padding(top = 12.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
        }
    }
}

/** Initials in a tinted disc. */
@Composable
fun Avatar(name: String, size: Dp = 52.dp, tone: Tone = Tone.Accent) {
    val initials = name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(2).joinToString("") { it.take(1).uppercase() }.ifEmpty { "?" }
    Box(
        Modifier.size(size).clip(CircleShape).background(toneSoft(tone)).border(1.dp, toneColor(tone).copy(alpha = 0.35f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(initials, style = MaterialTheme.typography.titleMedium.copy(fontSize = MaterialTheme.typography.titleMedium.fontSize * (size / 52.dp)), color = toneColor(tone))
    }
}

@Composable
fun Hairline(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().padding(vertical = 2.dp).heightIn(min = 1.dp, max = 1.dp).background(Pop.palette.hairline))
}
