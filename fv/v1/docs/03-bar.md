# Why BAR = 4474747

## Where it comes from

`server/pop/popt2.py:26`:

```
h = firwin(63, [2000, 18000], kaiser 6) scaled to max|h| = 127
g = rms gain 3–16 kHz            (~190 at 48 kHz)
B = round(g² / T0²),  T0 = 0.09   → 4474747   (44.1 kHz: 3792174)
```

- **0.09 (T0)** is the real choice: "score ≥ 0.09 = heard the beep". That was the intent. The spike showed the
  circuit's test doesn't guarantee it: silence and a blind 500 Hz tone can pass. See
  [05-spike-results.md](05-spike-results.md).
- **g** is the filter's gain, from the 63 taps.
- **4474747** is 0.09 translated into whole numbers so the circuit avoids square roots and decimals:
  `score ≥ T0` ⇔ `(I²+Q²)·g² ≥ T0²·E·cn2` ⇔ `(I²+Q²)·B ≥ E·cn2`. This only holds when `E·cn2 > 0`. With silence the
  score is 0/0, which is undefined, yet the whole-number test passes as 0 ≥ 0.

## Three layers, three answers

### Layer 1: is 4474747 the right translation of 0.09? FV yes, easy

Prove `BAR × match ≥ loudness` ⇔ real score ≥ 0.09, up to rounding, and state the rounding (about one part
in 10⁷ of the threshold). Same style as the `pair` proof.

Status: done in `Bar.lean`, for loudness above zero.

### Layer 2: is g right? FV yes, medium

g came from Python floats and was hard-coded ("the float design isn't portable"). Recompute it from the 63
integer taps with exact or interval arithmetic and prove the value. Catches a typo'd tap or a stale B
(check both 48k and 44.1k rows).

Status: half done. Lean proves any g in a narrow range rounds to B. `bar_check.py` shows the real g lands in that
range, to 60 digits. The value of g itself isn't in Lean. No circuit uses the 44.1k row.

### Layer 3: why 0.09 and not 0.05 or 0.2?

| Failure | Meaning | FV? |
|---|---|---|
| False accept (bar too low) | random sound or a cheater's audio passes | **yes**, as a probability theorem |
| False reject (bar too high) | a real beep in a real room fails | **no**, physics; measure on walks |

**The key move: take the randomness from the code, not the room.** The code is fresh and the cheater
doesn't know it ahead of time. Theorem shape:

> For **any** recording made without knowing the code, P(score ≥ 0.09 at any of the 193 lags) ≤ X.

**This shape is false as stated, for the test the circuit runs today.** Silence passes with P = 1. A 500 Hz tone at
amplitude 10000 passes about 95% of the time (57/60, replay). So gaps 1 and 2 in
[05-spike-results.md](05-spike-results.md) must be fixed first, or the theorem must leave those recordings out.

"Any recording" was meant to cover noise, music and attackers, with no room model. Today 0.09 is backed by a Gumbel fit
to the JBL250 walks (`bar_floor.py`, target 1e-4/3 per window). This would put a guaranteed X behind it.

Catch: the codes aren't white noise (band-limited JBL250 template, int8). The proof needs a model of how
random the code is, and X will be weaker than the textbook number. Working that out is the hard part; it's
the hardest piece of the whole FV list.

## Note

On v2 the app's bar is the same as the circuit's. The stricter `max(Gumbel, decoy max, floor)` in `PopDsp.kt:102` is
v1 code, and `PopRound2.kt:18` says it isn't run. On the Noir path, which the live guard doesn't use, the guarantee is `BAR × match ≥ loudness`. The live guard checks a server signature and runs no audio test. That test equals
"score ≥ 0.09" only when loudness is above zero. Judge any BAR theorem against that test.
