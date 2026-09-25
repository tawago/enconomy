# Phase 4 Campaign Runbook — Powered Distance Sweep & Tier Ladder

Date: 2026-07-11. Operator-facing procedure for the Workstream E campaign (fix-plan §6). This is
the turnkey guide: follow it top-to-bottom on two devices on a LAN and it produces the per-tier
go/no-go decision the project needs. It assumes Phases 0–3 have landed (band-parametric pipeline,
A2 validity guards, A3 timing prior, link-test gate, tier/condition stamping — all committed).

All commands assume your shell is in the project root:

```bash
cd research/proximity-echo        # (from the enconomy repo root)
```

`.venv/bin/python` is the pinned interpreter (numpy/scipy/pyroomacoustics). The trial log
`data/logs/trials.jsonl` is **real data** — the analysis tools only ever read it.

---

## 0. The decision you are making (go/no-go criteria, verbatim from fix-plan §6)

You are testing whether this commodity-browser setup can tell *proximity* (touch) apart from
*distance* (1 m), on **your** hardware, per hardware tier. The criteria, quoted exactly:

> **E1.** Hardware fallback ladder, each tier entered via the same link-test gate (≥ 0.5 both
> directions on the live meter): T1 fixed orientation (phone bottom-edge speaker aimed at the
> laptop mic); T2 band drop to 4–9 kHz (more omnidirectional speaker output); T3 external USB mic
> on the laptop (bypasses beamforming); T4 alternate phone. The browser-MVP go/no-go is *per tier*
> — "works only with an external mic" is a valid, reportable outcome.

> **E2.** Experiment design with power: collect until ≥ N *valid* trials per condition (rejected
> trials are re-collected, never counted), N chosen so a bootstrap CI on the touch-vs-1m score
> separation excludes zero — not a point-EER from 5 samples. Deaf and AEC rejections are logged per
> tier (they are data about the tier, not noise).

> **E3.** Threshold work happens only on this clean data; the paper's 0.78 was tuned on their
> hardware and their correctly-aligned channels. Band decision (6–12 vs 14–15 kHz) by *separation*,
> not absolute score, using the band-parametric pipeline (D3.5).

**Operationally:** a tier is a **GO** when the bootstrap confidence interval on the
touch-minus-1m score separation *excludes zero*. The campaign dashboard
(`analysis/campaign_status.py`) computes exactly this and prints `GO` / `NO-GO` / `PENDING` per
tier per band, for both the mean and the conservative `min(c_a,c_b)` scoring. `min(c_a,c_b)` is the
"both directions must agree" rule; treat it as the primary decision and `mean` as supporting.

---

## 1. Pre-campaign: prove the guards bite (deliberate-misconfiguration trials)

Before collecting a single real data point, run these **on purpose-broken** setups. Each must be
*rejected* with the right reason surfaced in the browser (fix-plan §8). If a guard does not fire,
the campaign data would be silently contaminated — stop and fix the guard first. Log these under
`condition = other`, label them (e.g. `misconfig-aec`), so they never enter the sweep.

| # | Deliberate misconfiguration | Expected outcome (must appear in the browser reasons) |
|---|---|---|
| 1 | **AEC on** — grant the mic with echo cancellation / voice isolation enabled (flip the browser/OS setting on) | `capture_valid=False`, reason contains `echo_cancellation` / `voice_isolation` (A2.7 hard guard); or `possible_aec_suppression` warning if the OS hides it |
| 2 | **Phone face-down** — phone flat, screen down, mic blocked by the desk | `capture_valid=False` on the phone side — `partner_inaudible` or `..._low_period_recovery` (deaf class), **not** an alias ACCEPT, **not** a crash |
| 3 | **Muted mic** — start a trial with one device's mic muted / permission denied | trial fails cleanly with a surfaced reason; the surviving client resets (no stuck "busy" latch) |

For any of these, if the outcome is unclear, generate the per-trial diagnostic report and confirm
the failure is named without touching WAVs:

```bash
.venv/bin/python analysis/inspect_trial.py <trial_id> --plot
# writes a self-contained HTML report to data/reports/
```

### Accumulated LIVE checklist carried over from Phases 2–3

These were implemented but never validated on live hardware (they need two real devices). Fold them
into this pre-campaign pass — they gate the trustworthiness of everything downstream:

- **A3 prior agreement:** run a normal near trial and confirm the logged `alignment_mode` is
  `prior_bounded` and the measured Δ agrees with the prior (a warning, never a rejection, on
  disagreement). Pre-A3 behavior must still score (dual-mode).
- **AEC reason in the UI:** misconfig #1 above — confirm the reason string actually renders in the
  browser, not just in the log.
- **Face-down diagnosability:** misconfig #2 above — confirm its report names the failure.
- **AEC-fingerprint false-positive rate:** the acoustic AEC fingerprint warns at threshold `0.015`
  and historically fired on ~10 weak-echo Android recordings. Watch for `possible_aec_suppression`
  warnings on *legitimate* (AEC-off) trials during collection; if they are frequent on your phone,
  note it — the threshold may need recalibration and it is warn-only so it will not block you.
- **Mid-trial disconnect:** pull one device off Wi-Fi mid-trial once; the other must emit/see a
  `trial_error` and reset rather than hang.

Only proceed to collection once the guards demonstrably fire and clean trials still score.

---

## 2. Start the server and open both devices

```bash
./run.sh serve
```

`run.sh` performs lightweight syntax checks and then serves HTTPS on port 5002. Automated tests and regression gates were removed for the experimental phase:

- Laptop (initiator): open `https://localhost:5002`
- Phone (observer): open `https://<laptop-LAN-IP>:5002` and accept the self-signed cert.

Tap **"Tap to Arm Audio"** on *both* devices (mobile browsers refuse scheduled audio without a
per-device gesture). Only the **initiator's** selectors (band preset, hardware tier, condition,
link test, Start) drive the trial — set everything on the laptop.

---

## 3. The tier ladder — enter a tier, pass its link-test gate, then collect

Work the ladder **in order**. Enter each tier, set the "Hardware tier" selector to match, pass the
link-test gate (§4), then collect the distance sweep (§5). A tier that never clears the gate both
ways is a legitimate, reportable NO-GO for that tier — move to the next.

### T1 — fixed orientation (no hardware change)

The MacBook mic is beamformed toward the user and is the binding constraint (replica-findings §3/§5:
6–12 kHz is bidirectionally audible in 15/16 non-control trials, but the laptop side is the weak
direction). Orientation is everything:

- Phone **screen-up**, its **bottom-edge speaker** offset just over the desk edge and **aimed at the
  laptop's mic** location (the one orientation that historically gave both directions ≥ 0.5).
- Avoid **face-down** — it flips the asymmetry (phone mic blocked, `c_b`→noise).
- Keep the surface, distance, and orientation **fixed** for the whole sweep; changing orientation
  mid-sweep changes the channel and pools non-comparable scores.
- Band stays at the default **6–12 kHz** for T1.

### T2 — band drop to 4–9 kHz (no hardware change)

Set the **"Band preset"** selector to **"4–9 kHz (T2 band drop)"** and the tier selector to **T2**.
4–9 kHz radiates more omnidirectionally from the phone micro-speaker, so it is the cheapest thing to
try when T1's laptop direction is deaf. No pipeline change is needed — the band is negotiated
end-to-end and the pipeline is band-parametric. Re-run the link test after switching the band (the
gate and the mic meter both follow the selected band). **Watch touch specifically at 4–9 kHz:** in
sim, near-field 4–9 kHz can let the laptop's partner echo fall under its own self-structure mask, so
confirm touch trials are still recoverable (capture_valid) and re-collect the ones that reject.

### T3 — external USB mic on the laptop (hardware change)

Plug a USB mic into the laptop (e.g. a cardioid desk mic) to **bypass the MacBook's beamforming** —
the single biggest lever, since the laptop mic is the weak direction. Select it as the input device
in the browser's mic permission prompt. Set tier **T3**, note the mic in the "Hardware notes" field.
Either band is fine; if T2's band already helped, keep 4–9 kHz. Re-run the link test.

### T4 — alternate phone (hardware change)

Android speaker HF radiation varies widely between models. If T1–T3 still fail the laptop or phone
direction, swap in a different phone, set tier **T4**, and note the model. Re-run the link test.

At each tier, record its outcome. "Works only with an external mic (T3)" or "only with an alternate
phone (T4)" are valid final answers for the browser MVP.

---

## 4. The link-test gate (run once per tier / orientation, before collecting)

The link test is a short reciprocal-audibility probe (8 beeps/device) that reuses the real trial's
capture + alignment path, so it measures the exact quantity a real trial scores from. It reports,
per direction, the **normalized partner audibility** `R = partner_train.median_amplitude /
self_train.median_amplitude` (how loud each device hears the other, normalized by its own beep). The
gate **passes when both directions clear `R ≥ 0.5`** (pinned as
`LINK_TEST_MIN_AUDIBILITY_RATIO`, anchored to replica-findings §3's amplitude survey — median 0.62
mac / 0.97 android — and 10× the pipeline's own inaudible floor).

1. Set band preset, hardware tier, and condition selectors on the laptop.
2. Click **"Run Link Test (both devices)"**. Both devices emit their train; each measures the other.
3. Read the per-direction pass/fail and the **Link gate** badge. If either direction is below 0.5,
   adjust orientation / advance a tier and re-run.

The gate **never hard-blocks collection** — a failed or absent gate is *stamped onto every
subsequent trial record* (the `link_test` block: present/passed/ratios/tier/band), so it is visible
in the log rather than refused. But do not collect a sweep through a failing gate: it will just
produce `partner_inaudible` rejections. The gate is your signal that a tier is worth collecting in.

> Note: the small "Mic level" meter lower on the page is a crude by-hand check, **not** the gate.
> The gate is the "Run Link Test" button.

---

## 5. Collect the distance sweep (per condition, driven by the dashboard)

For the tier whose gate passed, collect trials at each distance condition, set via the
**"Condition (distance)"** selector: `touch`, `30 cm`, `1 m`. (Use `other` + the free-text label for
anything else, e.g. a different-room control.) The decision is **touch vs 1 m**; 30 cm is a useful
intermediate.

Collection rules (fix-plan E2):

- **Only VALID trials count.** A rejected trial (deaf, AEC, clipping, ambiguous) is **re-collected,
  never counted** — but it is *not wasted*: the dashboard itemizes rejections per tier by reason,
  which is data about the tier.
- **Balanced N.** Aim for equal valid N in touch and 1 m — the power projection assumes balance.
- **Keep everything else fixed** within a tier's sweep: orientation, surface, band, devices.
- **Only gate-PASSED trials count.** The dashboard counts a valid trial toward the go/no-go only if
  it was collected under a passing link-test gate for its tier (§4). Trials collected under a failed
  or absent gate are shown separately as `gate-excluded (NOT counted)` — collect the sweep only
  after the gate passes.

> ⚠️ **Do NOT stop the moment a cell first reads GO.** Re-running the dashboard after every batch and
> stopping at the first GO is *optional stopping*, and it inflates the false-GO rate far above the
> nominal 5% — measured ~3× (≈15% cumulative over 5 looks) under a true null with no real
> separation. A GO harvested that way can be a stopping artifact, not a real effect. Do one of:
>
> - **Pre-register N (preferred).** After your *first* batch, read the `collect K more/group → N`
>   projection, commit to that **N**, collect up to it, and read the verdict **once** at N. The
>   "collect K more" number is a target, **not** a stop rule.
> - **Confirm a GO.** If a GO appears early, freeze the tier/band/scoring and collect a **fresh,
>   fixed-N** batch; only report the tier as GO if the replication also clears zero.
>
> The dashboard prints these cautions (optional stopping, multiple comparisons, small-N) in its
> `READ BEFORE TRUSTING A GO` footer — they are not optional reading.

Use the dashboard to track progress toward your pre-registered N:

```bash
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl --tier T2
```

A `GO` (CI excludes zero) for `min` scoring at your pre-registered N (and confirmed if it appeared
early) is the decision for that tier. `PENDING` with a "collect K more/group" number means keep
collecting toward N. A `NO-GO` with a stable, adequately-powered CI that straddles or sits below
zero means that tier does not separate — advance the ladder. **A GO flagged `[small-N: CI
anticonservative]` (fewer than 10 valid/group) is provisional** — the interval over-fires at that N
(see §7); collect to ≥ 10/group before trusting it.

---

## 6. How to read the dashboard

`analysis/campaign_status.py` is the campaign's single pane of glass. Default grouping is the
current pipeline generation → hardware tier → band, with both scoring rules.

```bash
# full dashboard, all tiers, current generation
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl

# one tier, JSON for archiving
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl --tier T3 --json

# skip the (slower) power projection for a quick look
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl --no-project
```

What each section means:

- **Per tier:** `valid trials/condition (gate PASSED, counted)` is your collection ledger — only
  gate-passed valid trials. `gate-excluded (NOT counted)` lists valid trials collected under a
  failed or absent link-test gate, per condition; they are shown so a tier collected through a
  failing gate cannot masquerade as collected, but they do **not** count toward the go/no-go.
  `rejected (by reason)` is the tier's failure fingerprint (lots of `partner_inaudible` ⇒ a deaf
  direction ⇒ advance the ladder).
- **Per band, per scoring (`mean`, `min`):**
  - `GO` — the bootstrap CI on touch-minus-1m separation excludes zero. Decision met (but heed the
    small-N flag and the cautions footer before trusting it).
  - `NO-GO` — CI includes/sits below zero at adequate power. No separation on this hardware.
  - `PENDING` — not enough valid trials yet; `insufficient_data` until ≥ 3/group.
  - `sep=+X CI[lo,hi] (bca)` — the separation and its 90% bias-corrected-accelerated interval.
  - `[small-N: CI anticonservative]` — appended when a group has fewer than 10 valid trials; at that
    N the interval over-fires (§7), so a GO is provisional until you collect to ≥ 10/group.
  - `collect K more/group -> N=…` — a power projection at the observed effect size, i.e. a target N
    to **pre-register** (§5), not a stop-when-you-hit-GO rule.
- **READ BEFORE TRUSTING A GO** — the footer restating optional stopping, multiple comparisons, and
  small-N. It is the honest fine print behind every GO; do not skip it.
- **BAND DECISION** (pools tiers): compares 6–12 vs 4–9 vs 14–15 kHz **by separation + CI**, never by
  absolute score — pick the band that separates most reliably (fix-plan E3), not the one with the
  highest touch score.
- **THRESHOLD SWEEP:** re-derives the verdict threshold (the paper's hardware-specific 0.78) from
  *your* valid distribution, reporting the equal-error threshold. For a rigorous per-band/per-tier
  sweep, use the dedicated tool:

```bash
.venv/bin/python analysis/sweep_thresholds.py data/logs/trials.jsonl \
    --positive-label touch --tier T2 --band 4-9kHz --score-mode min
```

For the raw descriptive counts (no statistics), `summarize_trials.py` groups
generation → tier → condition and now also reports per-condition band breakdown and the
`min(c_a,c_b)` mean:

```bash
.venv/bin/python analysis/summarize_trials.py data/logs/trials.jsonl
```

---

## 7. Deciding, and the statistics you are trusting

Report the outcome **per tier**: the lowest tier that reaches `GO` (min scoring), with its band, its
valid N per condition, the separation and CI, and the tier's rejection fingerprint. If no tier
reaches GO, report the best-powered NO-GO — that is a real, publishable result about commodity
browser hardware.

> ⚠️ **Multiple comparisons.** "The lowest tier that reaches GO" is picking the best cell out of a
> family of tests — up to 4 tiers × 2 bands × 2 scorings, plus the pooled band-decision table. Each
> cell is one look at a 5%-nominal test, so the chance that *some* cell shows GO by luck alone, on
> hardware with no real separation anywhere, is several times 5%. A **surprising, isolated GO** — GO
> on `min` but NO-GO on `mean`, or GO at only one band, or one lone tier — is exactly the shape a
> no-true-effect campaign throws off by chance. Before reporting such a GO, confirm it with a fresh
> fixed-N replication batch on that same tier/band/scoring. A GO that is consistent across `min` and
> `mean` and stable as N grows is the trustworthy kind.

Earlier statistical simulations produced the findings below. Their automated self-test runner has been removed; use real campaign data with the retained analysis tools.

- **null calibration** — on synthetic null data (true separation 0) at n = 20/group the BCa 90% CI
  includes zero at ~86–88% (near the 90% target within Monte-Carlo noise), and the percentile
  interval lands at essentially the same coverage. It prints both.
- **small-N calibration** — the same true-null draw at the small N a campaign actually collects
  (n ∈ {4, 6, 8, 10}). It prints the one-sided false-GO rate per N, which is **anticonservative below
  ~10/group** (measured ≈8–9% at n = 4–8 vs the nominal 5%). This is why an early GO carries the
  `small-N` flag and must be confirmed at a larger N — the very first dashboard check you see, after
  one 6–8 batch, runs at up to ~double the nominal false-positive rate before any optional-stopping
  compounding.
- **known power** — on a synthetic known effect, the projected N matches the analytic normal-approx
  N within a factor of ~2.
- **archive smoke** — runs on the real log and honestly reports `insufficient_data` (the archive is
  tiny and pre-fix), proving it does not crash on sparse data.
- **sim generated** — scores a handful of sim trials at two distances through the real pipeline and
  runs the full analysis on them.

Why BCa rather than a plain percentile interval: proximity scores are correlations capped at 1, so a
touch distribution piles up near the ceiling and the bootstrap separation is skewed — BCa is the
theoretically-preferred correction for that bias and skew. Be honest about what it buys, though: in
*this project's own* null calibration BCa and percentile come out within Monte-Carlo noise of each
other, and the dominant problem at campaign sample sizes is small-N under-coverage that hits **both**
methods (the small-N case above). So BCa is a reasonable default, not a fix for under-coverage;
neither interval reaches nominal coverage below ~10/group, which is what the small-N flag is warning
you about.

---

## 8. One-screen command reference

```bash
# --- collect ---
./run.sh serve                              # check syntax and start HTTPS server on :5002
#   laptop: https://localhost:5002   phone: https://<laptop-ip>:5002  (arm audio on BOTH)
#   set band preset + hardware tier + condition on the laptop; Run Link Test; then Start Trial

# --- monitor / decide (all read-only on the log) ---
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl                 # full dashboard
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl --tier T2       # one tier
.venv/bin/python analysis/campaign_status.py data/logs/trials.jsonl --positive touch --negative 1m
.venv/bin/python analysis/summarize_trials.py data/logs/trials.jsonl                # descriptive counts
.venv/bin/python analysis/sweep_thresholds.py data/logs/trials.jsonl \
    --positive-label touch --tier T2 --band 4-9kHz --score-mode min                 # rigorous per-band sweep
.venv/bin/python analysis/experiment_power.py data/logs/trials.jsonl \
    --positive touch --negative 1m --tier T2 --json                                 # one condition-pair, full report
#   (gate-passed trials only by default, matching the dashboard; add --include-ungated to see all)

# --- diagnose a single trial (no WAV inspection needed) ---
.venv/bin/python analysis/inspect_trial.py <trial_id> --plot        # HTML report -> data/reports/

# --- validate the statistics (seeded, reproducible) ---
.venv/bin/python analysis/experiment_power.py --validate
.venv/bin/python analysis/experiment_power.py --validate --with-sim
```
