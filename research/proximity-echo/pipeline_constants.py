"""Home for pipeline tunables introduced by the Phase-0 alias fix.

Policy (fix-plan.md D3.1/D3.2): every NEW tunable lives here with explicit units and a
one-line rationale, and none of them are absolute matched-filter-envelope thresholds —
everything is relative to per-recording measured quantities (noise floors, train
statistics) or to schedule geometry. Pre-existing constants remain in their historical
modules until the D3 consolidation phase.

Empirical numbers cited below come from docs/replica-findings.md (the A0 archive survey,
24 trials x 2 devices).
"""

# --- Schedule geometry -----------------------------------------------------------
# ms. Per-device emission period (two devices interleaved at 500 ms). Modules that have
# the trial schedule derive the period from it; this is the documented default for
# offline modules (validity) that only see summaries.
SCHEDULE_PERIOD_MS = 1000.0

# --- Pass-1 self search window (replica-findings §4.2) ---------------------------
# ms. An emission cannot precede its schedule slot by more than anchor jitter.
SELF_SEARCH_PAD_BEFORE_MS = 20.0
# ms. Widened from 230: true Android playout latency measured up to 306 ms in the
# archive (findings §3); 400 covers the observed range with margin.
SELF_SEARCH_PAD_AFTER_MS = 400.0

# --- Event-train detection (replica-findings §4.1.1) ------------------------------
# ms. Fold candidates within this circular distance merge into one cluster; also the
# min peak separation inside a slot window (matched-filter peaks are sub-ms wide).
TRAIN_CLUSTER_TOLERANCE_MS = 3.0
# ms. A cluster is an event train only if per-beep lag sigma (residual after removing
# linear drift) is below this; real 6-12 kHz trains measured sigma 0.10-1.7 ms.
# BAND-CALIBRATED: 6-12 kHz only. Measured 14-15 kHz per-beep jitter is 2.4-4.2 ms
# (android renders in 128-sample/2.67 ms quanta at that band). D3.5 revisited this: the
# band-scaled helpers below (train_coherence_sigma_ms, self_lock_sigma_ms,
# beep_refine_half_window_ms) add a 2.67 ms render-quantum allowance at/above
# HIGH_BAND_JITTER_MIN_START_HZ, so this constant, SELF_LOCK_MAX_SIGMA_MS, and
# BEEP_REFINE_HALF_WINDOW_MS remain the 6-12 kHz base values consumed through those helpers.
TRAIN_COHERENCE_MAX_SIGMA_MS = 2.0
# fraction. A train must be supported by at least this fraction of usable self slots —
# a per-trial-constant acoustic event repeats every period, noise does not.
TRAIN_MIN_SUPPORT_FRACTION = 0.5
# count. Minimum refined slots needed to estimate drift/sigma at all.
TRAIN_MIN_STAT_SLOTS = 3
# count. Top-N envelope local maxima considered per fold slot; 1-2 chirp trains plus a
# few echo-tail bumps are expected (findings §3), 6 leaves headroom without noise flood.
TRAIN_CANDIDATES_PER_SLOT = 6
# x (relative). Candidate peak must exceed this multiple of the slot-window median
# envelope (the local noise floor) — relative per D3.2, never absolute envelope units.
TRAIN_CANDIDATE_MIN_SNR = 8.0

# --- Per-beep anchoring / self-lock criterion (replica-findings §4.2) -------------
# ms. Per-beep tau1 is refined within +/- this of the train median lag.
# Band-calibrated to 6-12 kHz (see TRAIN_COHERENCE_MAX_SIGMA_MS note).
BEEP_REFINE_HALF_WINDOW_MS = 3.0
# ms. Per-beep coherence sigma below this = self lock. Replaces the absolute
# chirp_peak_value >= 1.0 gate (D3.2); real self trains measured sigma <= 1.7 ms.
# Band-calibrated to 6-12 kHz (see TRAIN_COHERENCE_MAX_SIGMA_MS note).
SELF_LOCK_MAX_SIGMA_MS = 1.5

# --- Joint self/partner train assignment (replica-findings §4.1.2) ----------------
# ms. Feasibility cut on the sum-identity residual delta_A + delta_B - (lat_A + lat_B
# - period) (mod period). The residual IS the round-trip air time (findings §2.2), so
# it scales with device separation: measured +0.13..+3.19 ms at touch..30 cm, and
# 2d/343 m/s gives 5.8 ms at 1 m, 11.7 ms at 2 m. 25 ms keeps assignments valid to
# ~4.3 m separation — the fix-plan §E distance sweep needs VALID far trials as its
# reject class. (Supersedes findings §4.1.2(i)'s "~5 ms", which budgeted only the
# touch/30 cm residuals + quantization.) Wrong labelings are rejected by the sign
# tie-break and satellite/drift ranking, not by this cut.
MAX_ROUND_TRIP_MS = 25.0
# ms. The sum residual equals the round-trip air time (positive by geometry, measured
# +0.13..+3.19 ms); assignments with residual below -this are the swapped labeling.
ROUND_TRIP_NOISE_FLOOR_MS = 1.0
# us/beep. Opposite-sign inter-device drift counts as supporting evidence only above
# this magnitude (~10 ppm at 1 s period); below it, common-mode drift dominates
# (findings §6.5), so drift never decides on its own.
DRIFT_SUPPORT_MIN_ABS_US_PER_BEEP = 10.0
# ms. Warn-only playout-latency priors per platform (findings §4.1.2(iii), §3).
SELF_LATENCY_PRIOR_MS = {
    "mac": (60.0, 150.0),
    "android": (80.0, 350.0),
}

# --- Self-structure mask (replica-findings §4.1.3-4) -------------------------------
# ms. Mask starts this early before each self-train beep position tau (peak-shape pad).
MASK_PAD_BEFORE_MS = 10.0
# ms. Mask extends beep_len + this past tau: measured self echo tail is < 5% of peak by
# +36 ms and < 1% by +60 ms; also covers the ~30-37 ms mac chassis reflection.
MASK_PAD_AFTER_BEEP_MS = 40.0
# ms. If the assigned partner train falls inside a self mask window, trim the mask to
# gap minus this and warn cross_partner_in_self_tail (small-gap guard; min observed
# gap 17.1 ms and nothing prevents ~0).
PARTNER_GAP_GUARD_MS = 5.0
# ms. Peak-to-peak extent of one emission's echo-tail family: a train this close AFTER
# a stronger train (and weaker than it) is treated as that train's satellite in the
# joint assignment. Measured tail bumps sit at +5/+10/+21 ms and decay below 1% of the
# peak by +60 ms; peak-to-peak lags do NOT scale with beep duration (matched filtering
# collapses the chirp), so this is deliberately independent of the mask span.
ECHO_TAIL_SPAN_MS = 60.0

# --- Masked cross-offset sweep (fix-plan A1.3) -------------------------------------
# ms. Sweep grid step (pre-existing value, homed here). A sweep-derived cross offset
# therefore carries up to +/- step/2 quantization error per device; the A2.5 sum check
# widens its tolerance by step/2 per sweep-derived operand so genuine sweep-fallback
# alignments are not flagged cross_offset_sum_inconsistent by grid error alone.
SWEEP_STEP_MS = 10.0
# count (of 20 cross beeps). Offsets with fewer unmasked predicted positions are
# ineligible — scoring a handful of leftover windows is not evidence.
SWEEP_MIN_UNMASKED_PREDICTIONS = 10
# x (relative). Masked sweep max below this multiple of the masked-envelope median
# (noise floor) => partner_inaudible; above it but failing the peakiness gate or the
# joint constraint => cross_offset_ambiguous (fix-plan A2.6 deaf-vs-ambiguous split).
PARTNER_INAUDIBLE_FLOOR_MULTIPLE = 3.0
# ms. Warn when the masked sweep argmax and the train-derived delta disagree by more
# than this (1.5 sweep steps); the train (sub-ms) wins, the warning flags the conflict.
SWEEP_TRAIN_DISAGREEMENT_WARN_MS = 15.0

# --- A2.1 self-alias overlap guard (fix-plan A2.1) ----------------------------------
# ms. A cross-beep chirp_start within +/- this of any masked self-structure position
# counts as one alias overlap.
ALIAS_OVERLAP_TOLERANCE_MS = 15.0
# count. More than this many overlaps => capture_valid=False with reason
# cross_selection_self_aliased (ca3013a2-class failures show 15-20 of 20).
ALIAS_OVERLAP_MAX_COUNT = 2
# ms. Overlap exemption for close-gap trials (nothing prevents gap ~0, findings §3):
# when the cross offset is train-assigned, a cross selection within this of its
# PREDICTED partner arrival (schedule + train-derived delta) is the partner, not an
# alias, even if the partner sits within ALIAS_OVERLAP_TOLERANCE_MS of self structure.
# Train predictions are sub-ms accurate; 5 ms covers residual drift across the trial.
ALIAS_PARTNER_MATCH_TOLERANCE_MS = 5.0

# --- A2.6 deaf-vs-ambiguous split via self-referenced sweep floor (fix-plan A2.6) --------
# fraction (of self-loop matched-filter amplitude). The masked-sweep noise floor is the
# median of a mostly-silent envelope (~0), so the old absolute 3x-floor test never fired
# on deaf channels (phase0-rescore anomaly): faint leakage cleared a ~0 bar. The principled
# reference for "what an AUDIBLE chirp arrival looks like" is the device's OWN self-loop
# matched-filter amplitude (self_train.median_amplitude) — a per-recording, self-normalized
# quantity (D3.2 compliant, never absolute envelope units). A masked-sweep best score below
# this fraction of the self loop means no partner is audible => partner_inaudible; above it
# but failing the peakiness gate => cross_offset_ambiguous. Calibrated on the archive:
# genuinely deaf sides (b933225d 0.01/0.0003, d6415a40 android 0.0009) sit far below,
# while the weakest AUDIBLE masked-sweep partner (d6415a40 mac 0.10, 1703c871 0.17/0.34)
# sits above; 0.05 separates them with ~2x margin either way. Train-assigned offsets are
# EXEMPT (the joint assignment already vetted a real partner — the weakest genuine partner
# train, 2e7904fa at 1 m, scores only 0.02 of self yet is a true, drift-locked arrival).
PARTNER_INAUDIBLE_SELF_FRACTION = 0.05

# --- A2.2 self-grid coherence guard (fix-plan A2.2, replica-findings §4.1.6) -------------
# ms. Circular distance of (cross_offset - self_offset) mod the 500 ms interleave to the
# danger-lag set {0}. At (cross - self) == 0 (mod 500) the partner-prediction grid coincides
# with the device's own emission grid, so the cross channel risks re-measuring self. The
# danger-lag set is EXACTLY {0} at the CORRECTED self latency (replica-findings §4.1.6: no
# replica lags exist). Calibrated on the archive: every correctly-aligned partner-train
# trial has |grid lag| >= 66 ms, while genuine near-coincidences (1703c871 +/-18, d6415a40
# -6.6, b933225d -24, d4624efe 22) sit below 40 ms; 40 ms flags the coincidences without
# touching a single aligned trial.
GRID_COHERENCE_TOLERANCE_MS = 40.0
# fraction (of self-loop amplitude). A grid-coherent cross offset is rejected UNLESS its
# matched-filter score independently clears this high bar relative to the self loop (a loud,
# unambiguous partner on the self grid is a real near-collision, not a self-latch). Set
# above the weak/ambiguous masked-sweep survivors (d6415a40 mac 0.10) and below the genuine
# near-collision partners (1703c871 0.17/0.34) so only the weak grid-coincident offsets are
# rejected as self-grid-coherent.
GRID_COHERENCE_CLEAR_SELF_FRACTION = 0.15

# --- A2.3 cross-channel spectral self-similarity guard (fix-plan A2.3) -------------------
# Pearson. When the (uncompensated) cross-channel echo signature correlates with the
# device's OWN self-channel echo signature above this AND the offset is grid-coherent
# (A2.2), the cross channel is re-measuring the same physical self echo => self-alias,
# reject. High similarity ALONE never rejects (a legitimate beside-each-other pair has
# cross ~ self); the grid-coherence conjunction is required. Calibrated on the archive: no
# correctly-aligned trial pairs high similarity with grid coherence; 0.70 catches a clear
# self-echo re-measurement (d4624efe's dubious 22 ms "partner" at sim 0.77) and the sim's
# double-self-alias negatives, whose cross re-measures self at ~1.
CROSS_SELF_SIMILARITY_MAX = 0.70

# --- A2.4 cross/self energy plausibility (fix-plan A2.4) — WARN-ONLY ----------------------
# ratio (cross-channel median chirp peak / self-channel median chirp peak). Review showed
# this both MISSES quiet aliases (~10% amplitude) and FALSE-POSITIVES the paper's primary
# beside-each-other scenario (cross ~ self is legitimate), so it NEVER gates — it is logged
# as a warning only. Warn when the ratio falls outside [low, high]: the archive spans
# 0.0-32 (median ~1), so a [0.02, 20] band flags only extreme imbalances for forensics.
CROSS_SELF_ENERGY_WARN_LOW = 0.02
CROSS_SELF_ENERGY_WARN_HIGH = 20.0

# --- A2.7 AEC / OS voice-processing guard (fix-plan A2.7) --------------------------------
# fraction (self-channel median echo peak / median chirp peak). Browser/OS AEC cancels the
# known playback reference, collapsing the self echo period relative to the self chirp peak.
# WARN-ONLY (possible_aec_suppression): on this beamformed-mic hardware the echo is already
# genuinely weak, so the fingerprint is a heuristic, not a gate. Set low so it flags only a
# near-total collapse; the sim aec_on() scenario drives it well below this while the sim
# positives sit above.
POSSIBLE_AEC_ECHO_FRACTION = 0.015

# --- A2.8 cross_offset_score floor (fix-plan A2.8) --------------------------------------
# A masked-sweep-sourced cross offset (NOT train-vetted) must clear a floor to be trusted.
# The floor is the MAX of a masked-noise-floor multiple (principled but ~0 on these mostly-
# silent envelopes) and a self-loop fraction (the robust, self-normalized backstop). Set the
# self fraction equal to the A2.6 inaudible fraction so A2.8 is the validity-layer echo of
# A2.6's alignment-layer classification: a masked-sweep offset that slipped past the sweep
# yet scores below this of the self loop is flagged cross_offset_below_floor. Train-assigned
# offsets are exempt (vetted by the joint assignment).
CROSS_OFFSET_SCORE_NOISE_FLOOR_MULTIPLE = 3.0
CROSS_OFFSET_SCORE_SELF_FRACTION = 0.05

# --- D3.7 clipping severity + per-beep localization (fix-plan D3.7) ----------------------
# The old single-sample trip (clipped_sample_count > 0 => trial-fatal) withheld ~8 archive
# trials whose clipping is a handful of isolated samples (measured: fractions 8e-5..2e-2,
# longest contiguous run 0.02..0.67 ms) — cosmetic saturation that does not corrupt the
# matched filter. D3.7 replaces it with fraction + duration thresholds and per-beep window
# localization. Clipping thresholds are legitimately in PCM full-scale units (clipping is
# DEFINED at +/-1.0 full scale, a hardware-independent physical fact — NOT a matched-filter
# envelope threshold, so D3.2's de-absolutization does not apply here).
# fraction of total samples at/above full scale beyond which the WHOLE recording is treated
# as saturated (fatal). 5% is far above every archive trial's isolated clipping (max 2%).
CLIP_FATAL_FRACTION = 0.05
# ms. A single contiguous clipped run this long or longer is genuine sustained saturation
# (a chirp driven hard into the rails), fatal regardless of the total fraction. 5 ms is ~1/5
# of a 25 ms chirp and ~7x the longest archive run (0.67 ms).
CLIP_FATAL_RUN_MS = 5.0
# ms. Pad added around each beep's chirp+echo window when localizing which beeps a clipped
# run corrupts. Covers matched-filter smear at the window edges.
CLIP_LOCALIZE_PAD_MS = 2.0
# ms. A beep window is only EXCLUDED from the signature stack when it contains a contiguous
# clipped run at least this long — sustained saturation that genuinely flattens part of the
# chirp/echo. Isolated single-sample clips (the archive's entire clipping population:
# scattered <=0.67 ms runs) are cosmetic and must NOT exclude the beep, or a handful of
# rail-touching peaks would wipe out most of a device's signature. 0.5 ms is ~2% of the
# 25 ms chirp; below it the matched filter is essentially unaffected.
CLIP_BEEP_EXCLUDE_RUN_MS = 0.5

# --- A3 timing prior: prior-bounded cross-offset sweep (fix-plan A3.2/A3.3) ---------------
# The cross offset for device A is Delta_A = lat_B (partner playout latency) + record-start
# skew (findings §2.4 sum identity). When A3 client metadata is present (websocket time
# probes give the inter-device clock skew via offset_vs_server; a first-onaudioprocess
# (Date.now, currentTime) anchor pins each WAV sample 0 to wall-clock time), the server can
# center the masked sweep on that predicted Delta and search only a MEASURED-uncertainty
# window around it instead of the full +/-900 ms. This kills the far/1000 ms alias family and
# wild sweeps; it does NOT structurally exclude the +/-500 ms self-alias (its band overlaps
# the true-offset band, fix-plan §1.2), so the A2 guards still decide rejection. DUAL-MODE
# (A3.3): the prior is applied ONLY when the metadata is present and sufficient; pre-A3 WAVs
# (the archive, the goldens) carry no timing metadata and fall back to the Phase-0 full sweep,
# scoring byte-identically forever.
#
# ms. Fixed half-window covering the terms NOT measured per-trial: partner self-latency
# measurement spread (per-beep sigma <=1.7 ms) + playout jitter + round-trip air time
# (<=~12 ms at 2 m). 40 ms is generous headroom over those.
A3_PRIOR_BASE_HALF_WINDOW_MS = 40.0
# fraction. Clock-offset uncertainty from the time probes enters the half-window as this
# fraction of the summed min-RTTs of the two devices (min-RTT halves the one-way skew error;
# summing the two devices' terms is conservative). 0.5 => half of each device's min-RTT.
A3_PRIOR_RTT_HALF_WINDOW_FRACTION = 0.5
# ms. Sample-0 anchoring residual: the lag between the audio hardware capturing WAV sample 0
# and the first onaudioprocess callback that stamps it (base latency + up to one 4096-sample
# ScriptProcessor render quantum, ~85 ms at 48 kHz). Added to the half-window so a mis-pinned
# anchor cannot push the true offset outside the search band.
A3_PRIOR_ANCHOR_HALF_WINDOW_MS = 90.0
# ms. Hard cap on the prior half-window regardless of measured RTT: the search band must stay
# narrower than the 250 ms half-distance to the +/-500 ms self-alias so a noisy network cannot
# widen the window until it re-admits the alias family the prior exists to exclude.
A3_PRIOR_MAX_HALF_WINDOW_MS = 240.0
# ms. A3.4: WARN (never gate — the guards decide) when the finally-measured cross offset lands
# more than the prior half-window plus this margin away from the prior center. The margin
# absorbs the sweep grid step and sub-window drift so only a genuine prior/measurement conflict
# is flagged cross_offset_outside_prior.
A3_PRIOR_DISAGREEMENT_MARGIN_MS = 15.0

# --- Workstream E link-test gate (fix-plan §E1) -------------------------------------------
# The reciprocal-audibility gate that admits each hardware tier (T1..T4). The gate quantity is
# the NORMALIZED PARTNER AUDIBILITY per direction:
#
#     R_dir = partner_train.median_amplitude / self_train.median_amplitude
#
# a dimensionless ratio of the peak matched-filter amplitude of the ASSIGNED partner beep train
# to the peak matched-filter amplitude of the LISTENING device's OWN beep train. Both operands
# are the SAME per-recording measurement (EventTrain median peak amplitude, feature_extraction
# EventTrain.summary) taken on the partner grid vs the self grid, so the ratio is self-
# normalized (D3.2-compliant, never absolute envelope units) and reads directly as "how loud
# does the partner arrive vs how loud I hear my own beep". One value per direction: R at device
# A (A-hears-B) = A's partner-train peak / A's self-train peak; R at device B (B-hears-A)
# symmetric. The gate passes only when BOTH directions clear the bar. A direction with NO
# assigned partner train (a deaf/ambiguous link the joint alignment could not confidently place)
# is indeterminate and treated as a FAIL.
#
# (An earlier draft used cross_offset_score/self_reference_amp, but cross_offset_score is a
# ±window MEAN of the masked envelope — ~20-30x smaller than a peak — so it is NOT on the same
# scale as the self-train peak and mis-mapped onto §3's peak/peak survey; the two train medians
# are the apples-to-apples quantity, confirmed in the sim + scripted harness.)
#
# THRESHOLD MAPPING (fix-plan §E1 asks for "≥ 0.5 both directions" but leaves the UNITS
# unspecified). R_dir is the principled unit and 0.5 is adopted directly on it: the partner must
# arrive at least half as loud (peak matched-filter) as the device hears its own beep. Anchors:
#   • replica-findings §3 partner/self amplitude-ratio survey (peak/peak, the SAME quantity) —
#     median 0.62 (mac) / 0.97 (android), range 0.1–11, partner ≥ self in 18/43 recordings — so
#     0.5 sits just below the mac-side median, and the mac/laptop side (the documented weak
#     direction) is the binding one.
#   • 0.5 == 10× the pipeline's own PARTNER_INAUDIBLE_SELF_FRACTION (0.05) inaudible floor, i.e.
#     a decisively-audible bar well clear of the deaf/ambiguous band the A2.6 split lives in.
# The gate NEVER hard-blocks collection (diagnostic trials under a failed/absent gate are still
# allowed and logged) — it only STAMPS pass/fail onto the session's subsequent trials so an
# uncovered trial is visible in the log, exactly as the regression stamp does for code coverage.
LINK_TEST_MIN_AUDIBILITY_RATIO = 0.5
# count. Beeps per device in the fast link-test probe (a full trial uses 20). Enough for robust
# train detection (≥ TRAIN_MIN_STAT_SLOTS=3 with margin, ≥ TRAIN_MIN_SUPPORT_FRACTION support)
# and a stable median R, while keeping the probe short: record window ≈ lead-in + (2·N−1)·500 +
# tail ms, so N=8 ⇒ ~9.5 s vs ~22 s for a full 20-beep trial.
LINK_TEST_BEEPS_PER_DEVICE = 8

# =====================================================================================
# D3.1 legacy-constant consolidation + D3.2/D3.3/D3.4/D3.5 (fix-plan §D3)
#
# Every value below was previously an inline literal or a module-local constant in one of
# alignment.py / feature_extraction.py / scoring.py / compensation.py / validity.py /
# clipping.py / challenge_generator.py (see the Phase-3 constants inventory). They are homed
# here with units + rationale. All values are chosen so the 6-12 kHz archive re-scores
# BYTE-IDENTICALLY (pure moves + no-op band parametrization); the intentional numeric movers
# are D3.4 (SMOOTH_WINDOW_HZ) and D3.6 (compensation interpolator), which live in their own
# modules. pipeline_constants imports NOTHING from the pipeline, so homing protocol constants
# (BEEP_*, CANONICAL_SAMPLE_RATE) here introduces no import cycle: the owning modules re-export.
# =====================================================================================

# --- Protocol audio format (was challenge_generator.CANONICAL_SAMPLE_RATE) --------------
# Hz. The single canonical capture rate the whole pipeline resamples to; every ms<->sample
# conversion and the clipping run-length metric assume it.
CANONICAL_SAMPLE_RATE = 48_000

# --- Beep-template protocol defaults (was challenge_generator.BEEP_*) --------------------
# Per-trial BeepSpec overrides these; they are the current-generation defaults only. 6-12 kHz
# is the reach-friendly band (above HVAC/voice noise, within phone+laptop high-SPL response,
# wide enough for a clean matched-filter time-bandwidth product). Amplitude 0.35 avoids ADC
# clipping at touch distance. Duration 20 ms matches Ren et al. INFOCOM'21 (fits CHIRP_PERIOD).
BEEP_DURATION_MS = 20
BEEP_START_FREQ_HZ = 6_000.0
BEEP_END_FREQ_HZ = 12_000.0
BEEP_AMPLITUDE = 0.35
BEEP_FADE_MS = 3

# --- Period selection (was alignment.py module constants) --------------------------------
# ms. Chirp-period / echo-period segment lengths (paper §IV-B). Physical protocol facts.
CHIRP_PERIOD_MS = 25
# ms. Keep the full template plus this safeguard before searching for echoes.
# The standard 20 ms template gives 25 ms; archived 40 ms templates require 45 ms.
CHIRP_GUARD_MS = 5.0
ECHO_PERIOD_MS = 100
# ms. Algorithm-1 sliding-window width for local-max thinning (was 480 samples @48k = 10 ms;
# re-denominated in ms per D3, converted to samples at the canonical rate at import).
LOCAL_MAX_WINDOW_MS = 10.0
# ms. Post-chirp reflection search span (was 9600 samples @48k = 200 ms).
ECHO_SEARCH_RANGE_MS = 200.0
# fraction of the local-max envelope. τ1 chirp-peak acceptance ratio (already relative).
CHIRP_PEAK_THRESHOLD_RATIO = 0.30
# Nominal probability budget per period search under a Rayleigh noise-envelope model.
# Replaces the old 3*median / 2%-of-direct echo cutoff, which rejected weak reflections.
# The median is estimated, so this is a model-based gate, not a universal error bound.
PERIOD_SEARCH_FALSE_ALARM_BUDGET = 0.001
# Fraction of the direct matched-filter peak. Float32 resolution covers numerical
# residue in a noiseless direct-only recording, including ideal bandpass ringing.
ENVELOPE_RELATIVE_PRECISION_FLOOR = 2.0 ** -23
# Hz. Bandpass guard margin added on each side of the beep band before filtering. The band
# edges themselves come from the trial's beep_spec (D3.5), not from module constants.
BANDPASS_GUARD_MARGIN_HZ = 500.0
# ms. Default select_periods_for_beep search pads (lopsided: Android/Chrome buffers 150-300 ms
# of output latency before the speaker fires, so the window reaches further AFTER the slot).
SELECT_SEARCH_PAD_BEFORE_MS = 100.0
SELECT_SEARCH_PAD_AFTER_MS = 350.0
# envelope units. Numerical floor added to medians before division (matched-filter envelope).
ENVELOPE_FLOOR_EPS = 1e-12

# --- Masked cross-offset sweep (was feature_extraction.py inline literals) ---------------
# ms. Half-range of the ±offset sweep. Capped below the 1000 ms far-alias (adjacent self beep)
# so offset and offset±period do not both score high.
SWEEP_SEARCH_HALF_RANGE_MS = 900.0
# ms. ±window averaged around each predicted cross position when scoring an offset
# (was 0.005*sample_rate = 5 ms).
SWEEP_PREDICTION_TOL_MS = 5.0
# x. Peakiness gate multiples: the masked-sweep best score must exceed the larger of the 25th
# percentile × P25 and the median × MEDIAN of the eligible-offset score distribution.
SWEEP_PEAKINESS_P25_MULTIPLE = 6.0
SWEEP_PEAKINESS_MEDIAN_MULTIPLE = 4.0
# ms. Pass-3 cross-beep per-beep search pad around schedule+cross_offset (both sides).
CROSS_BEEP_SEARCH_PAD_MS = 200.0

# --- Scoring (was scoring.py module constants) -------------------------------------------
# Pearson score. Paper acceptance threshold c_th.
DEFAULT_VERDICT_THRESHOLD = 0.78
# Hz. Boxcar smoothing bandwidth for the echo-period signatures (D3.4). Historically this was
# SMOOTH_WINDOW_FREQ_POINTS = 20 FFT *bins*, whose bandwidth in Hz silently changed with the
# echo-segment duration (the bin spacing). Re-denominated in Hz and converted to bins at
# runtime from the actual echo-grid resolution. The 100 ms echo segment at 48 kHz yields a
# 10 Hz rfft bin, so 20 bins == 200 Hz — this value reproduces the historical smoothing on the
# 6-12 kHz archive exactly while staying band/duration invariant.
SMOOTH_WINDOW_HZ = 200.0

# --- Compensation (was compensation.py EPS) ----------------------------------------------
# energy units. Division floor in the compensation ratio and interpolation clamps.
COMPENSATION_EPS = 1e-12

# --- Validity (was validity.py module constants) -----------------------------------------
# fraction of a channel's beeps with a valid period selection below which the channel is
# flagged low_period_recovery.
MIN_SELECTION_OK_RATIO = 0.60
# count of echo-grid frequency points below which the signature is too sparse to score.
MIN_SIGNATURE_FREQ_POINTS = 8
# x noise-floor multiple. D3.2: replaces the absolute MIN_MEDIAN_CHIRP_PEAK = 0.02 (matched-
# filter envelope units, which silently changed meaning with BEEP_AMPLITUDE / band / template
# length). A channel's direct path is "weak" when its median chirp peak is below this multiple
# of the LISTENING device's per-recording matched-filter noise floor (sweep.noise_floor_env) —
# self-referenced, band-independent. Calibrated on the archive: every real direct path clears
# the noise floor by ≥4500×, while genuinely absent channels (median peak == 0) fall below any
# positive multiple, so this reproduces the archive's exact weak_direct_path fires.
WEAK_DIRECT_PATH_NOISE_FLOOR_MULTIPLE = 3.0

# --- Clipping detection threshold (was clipping.py default 0.99) -------------------------
# PCM full-scale rail. Sample magnitude at/above which a sample is counted clipped. Legitimately
# absolute (clipping is DEFINED at ±full scale — a hardware-independent physical fact; D3.2's
# de-absolutization does not apply to the clipping rails).
CLIP_DETECT_THRESHOLD = 0.99

# --- D3.5 band parametrization ------------------------------------------------------------
# The pipeline's frequency-dependent parameters must come from the trial's beep_spec, not from
# the 6-12 kHz module constants, so the 14-15 kHz archive (and any future band) is scorable.
# These helpers take primitive floats (never BeepSpec) to keep pipeline_constants import-free.

def bandpass_edges_hz(start_freq_hz: float, end_freq_hz: float) -> tuple[float, float]:
    """Bandpass edges for a beep band = [start - margin, end + margin]. For the 6-12 kHz
    defaults this returns (5500, 12500), identical to the historical alignment.py constants."""
    return (float(start_freq_hz) - BANDPASS_GUARD_MARGIN_HZ, float(end_freq_hz) + BANDPASS_GUARD_MARGIN_HZ)

# Hz. At or above this start frequency the archive's captures were taken by an Android client
# whose WebAudio ScriptProcessor quantizes playout onto 128-sample (2.67 ms) render quanta,
# inflating per-beep timing jitter to 2.4-4.2 ms (replica-findings §3) — well beyond the
# 6-12 kHz coherence gates (σ 0.1-1.7 ms). Below this threshold the gates are unchanged, so the
# 6-12 kHz archive is byte-identical; at/above it they gain a one-render-quantum allowance.
HIGH_BAND_JITTER_MIN_START_HZ = 13_000.0
# ms. One WebAudio render quantum (128 samples) at the canonical rate = 2.667 ms.
RENDER_QUANTUM_JITTER_MS = 128.0 / CANONICAL_SAMPLE_RATE * 1000.0


def _render_quantum_allowance_ms(start_freq_hz: float) -> float:
    return RENDER_QUANTUM_JITTER_MS if float(start_freq_hz) >= HIGH_BAND_JITTER_MIN_START_HZ else 0.0


def train_coherence_sigma_ms(start_freq_hz: float) -> float:
    """Max per-beep lag σ for a cluster to count as an event train, band-aware (D3.5).
    Returns TRAIN_COHERENCE_MAX_SIGMA_MS (2.0) for the 6-12 kHz band; adds one render quantum
    for the render-quantized high band."""
    return TRAIN_COHERENCE_MAX_SIGMA_MS + _render_quantum_allowance_ms(start_freq_hz)


def self_lock_sigma_ms(start_freq_hz: float) -> float:
    """Per-beep σ below which the self train counts as locked, band-aware (D3.5). Returns
    SELF_LOCK_MAX_SIGMA_MS (1.5) for 6-12 kHz; adds one render quantum for the high band."""
    return SELF_LOCK_MAX_SIGMA_MS + _render_quantum_allowance_ms(start_freq_hz)


def beep_refine_half_window_ms(start_freq_hz: float) -> float:
    """Per-beep τ refinement / self-selection half-window, band-aware (D3.5). Returns
    BEEP_REFINE_HALF_WINDOW_MS (3.0) for 6-12 kHz; adds one render quantum for the high band."""
    return BEEP_REFINE_HALF_WINDOW_MS + _render_quantum_allowance_ms(start_freq_hz)


# =====================================================================================
# C3 pipeline version + constants snapshot (fix-plan §C3)
#
# PIPELINE_VERSION identifies the end-to-end scoring behavior. BUMP POLICY: increment it on
# ANY change that can move a trial's numeric score, verdict, failure reasons, warnings, or
# the meaning of a logged field — a new/removed guard, a retuned constant below, a changed
# interpolator, a band-parametrization change, a schema field that alters interpretation.
# Pure refactors that are provably byte-identical on the archive (D3.1-style constant moves)
# do NOT require a bump, but when in doubt, bump: an un-bumped behavior change is exactly how
# the log became uninterpretable (feature_version/classifier_version were never bumped on
# retunes). The paired constants_snapshot() below records the actual tunable VALUES so a
# record stays interpretable even across an un-bumped drift — the hash changes even if the
# version string does not.
#
# Version history:
#   proximity_echo_pipeline_v1 — first stamped version. Pipeline state as of Phase 3:
#     paper_repro feature_version, validity v3 (A2.1-A2.8 guards), joint train assignment,
#     self-structure masking, D3.7 clipping localization, A3 dual-mode timing prior,
#     D3.1-D3.6 constants consolidation + band parametrization + PCHIP compensation.
#   proximity_echo_pipeline_v2 — Phase-4 Workstream E (tier ladder + link-test gate). Adds the
#     reciprocal-audibility link-test gate (LINK_TEST_* constants) and the tier/condition/
#     link-test record fields (LOG_SCHEMA_VERSION 6). Purely ADDITIVE to the scoring path: a
#     normal trial's score/verdict/reasons/warnings are byte-identical to v1 (the archive
#     re-scores and every golden are unmoved). Bumped anyway per the "when in doubt, bump"
#     policy because a new derived gate + new logged fields entered the record.
#   proximity_echo_pipeline_v3 — onset-indexed correlation, noise-based period gates,
#     complete unmasked period slices, and selection diagnostics (log schema 8).
# =====================================================================================

PIPELINE_VERSION = "proximity_echo_pipeline_v3"

import hashlib as _hashlib  # noqa: E402  (stdlib only; keeps the no-pipeline-import invariant)
import json as _json  # noqa: E402

# Names that are UPPER_CASE but are NOT behavioral tunables (meta/version identifiers), so
# they are excluded from the constants snapshot to keep the hash a pure function of the knobs.
_SNAPSHOT_EXCLUDE = {"PIPELINE_VERSION"}


def constants_values() -> dict:
    """The current values of every tunable homed in this module, as a plain JSON-able dict
    (name -> value). Introspects module globals so a newly-added constant is captured
    automatically — no hand-maintained list to drift out of date."""
    values: dict = {}
    for name, value in globals().items():
        if name.startswith("_") or name in _SNAPSHOT_EXCLUDE:
            continue
        if not name.isupper():
            continue  # skip helper functions (lower_case) and imported modules
        if isinstance(value, (int, float, str, bool, tuple, list, dict)):
            values[name] = value
    return dict(sorted(values.items()))


def constants_snapshot() -> dict:
    """C3 constants snapshot for a trial record: the full tunable dict plus a stable content
    hash, so a record is interpretable after any future retune (the values are self-describing
    and the hash detects drift even when PIPELINE_VERSION was not bumped)."""
    values = constants_values()
    blob = _json.dumps(values, sort_keys=True, default=list)
    digest = _hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return {
        "pipeline_version": PIPELINE_VERSION,
        "constants_hash": "sha256:" + digest,
        "constants": values,
    }
