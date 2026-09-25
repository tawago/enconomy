# Proximity-Echo Reproduction — Complete Fix Plan (v2)

> Historical record. Automated tests and regression gates were removed at the user's request on 2026-09-22. Old test commands below no longer apply; follow [the current workflow](../AGENTS.md).

Date: 2026-07-07. Supersedes the "what to do next session" section of
[progress-report-proximity.md](progress-report-proximity.md).

v2 after adversarial review: a first draft's mask design was **empirically refuted on
the archived WAVs** during review — implementing it exactly as specified still selected
the aliased offsets on `ca3013a2`, because of a previously unknown *self-replica* in the
recordings (§1.2). This version redesigns Workstream A around that finding and folds in
~20 further review corrections. Where v1 claimed "three independent layers, any one of
which prevents the failure", v2 claims layered *defense with one decisive guard*: only
the self-overlap/spectral guards (A2) are unconditionally sound; masking (A1) and timing
priors (A3) reduce how often the guards must fire.

## 0. Executive summary

The reproduction "worked once and never again" because of a **cross-device alignment
aliasing bug**, not (only) the documented hardware asymmetry. The cross-offset estimator
(`feature_extraction.py::_estimate_cross_device_offset_ms`) locks onto each device's own
beeps — which sit exactly ±500 ms (the interleave spacing) plus playout latency away
from the partner's schedule slots and are far louder than the partner's beeps. Once
aliased, the "cross-device" channel silently re-measures each device's **self**-echo,
and the Pearson score compares self-echo vs self-echo — physically meaningless for
proximity.

Evidence (verified 2026-07-06/07 on the archived WAVs and in simulation):

- Trial `ca3013a2` (the only ACCEPT, score 0.866): **20/20** "partner" selections on the
  laptop and **15/15** on the phone are at *sample-identical* positions to the device's
  own beeps. Same class of failure in `e45a9b51`, `1703c871`, and every May-12 trial
  (laptop offsets clustered −290…−420 ms, phone +610…+790 ms — all self-aliases, of two
  distinct flavors, see §1.2).
- Correctly-aligned trials (e.g. `fedbaf73`) score *lower* than aliased ones because the
  true cross channel is weak on this hardware (beamformed MacBook mic). The threshold is
  crossed by the artifact, not the signal.
- The 3D simulation (`simulation/`) reproduces the bug on demand — and is itself
  contaminated by it: the phone side self-aliases in **every** scenario ever run,
  including the "favorable" positives behind the README validation table. Additionally
  the default phone preset (`clock_offset_ms=320` + `output_latency_ms=180` = exactly
  500 ms) collides the interleaved schedules by construction, so in "favorable" scenes
  the laptop's *self* selections grab the *phone's* beeps.
- A latent `TypeError` (`feature_extraction.py:204-212` constructs `PeriodSelection`
  with nonexistent `*_sample` kwargs) crashes the pipeline whenever the sweep returns
  `None` — so the one existing "can't trust alignment" rejection path has never fired.
- **New (found in review):** recordings contain a discrete **self-replica** ~128 ms
  after each detected self beep, phase-locked to the self grid on *both* devices
  (verified on `ca3013a2`: a second arrival at +128 ms comparable to or larger than the
  detected peak). The aliased offsets −290/+740 equal `±500 + self_offset + 128` — the
  sweep locked onto the *replica*, not the main peak. Any fix that masks only detected
  self peaks fails; root-causing this replica is now the first work item (A0).

Non-goals for now: replay/MiM attack experiments (paper §V-D/E), multi-device pairs,
native (non-browser) capture. These come after touch-vs-distance separation lands.

## 1. Why the alias exists (mechanics)

### 1.1 Basic mechanism

The schedule interleaves beeps: initiator at 1000, 2000, …; observer at 1500, 2500, … ms
(500 ms apart, 1000 ms per-device period). Each device interprets offsets in its own
recording clock, so the partner's beeps land at `schedule + Δ`, where
`Δ = clock skew + partner playout latency` is unknown (±hundreds of ms).

`_estimate_cross_device_offset_ms` sweeps candidate Δ in ±900 ms, scoring each by the
matched-filter envelope at the predicted partner positions. Shifting the *partner* grid
by `±500 + own playout latency` lands it exactly on the device's **own** beep grid — and
self-locked energy is 10–1000× louder than the partner (near-field). The sweep's global
maximum is therefore a self-alias whenever true cross peaks are weaker than self-locked
peaks — on this hardware *always* for the laptop, *usually* for the phone. The ±900 ms
cap only guards the 1000 ms alias (same device's next beep), not the 500 ms one.

### 1.2 Two alias flavors (this distinction drives the design)

Both grids (self and partner) have the same 1000 ms period; they differ only in phase.
The observed aliases come in two flavors:

- **Main-peak alias:** `Δ_alias = ±500 + self_latency` — the sweep lands on the detected
  self peaks (e.g. `e45a9b51` laptop at −420 ≈ −500 + 80).
- **Replica alias:** `Δ_alias = ±500 + self_latency + ~128 ms` — the sweep lands on the
  self-replica (e.g. `ca3013a2` laptop −290 ≈ −500 + 82 + 128; phone +740 ≈ +500 + 115
  + 128... within sweep quantization). Verified by envelope profiling on both devices.

Consequences:

- **The antisymmetry invariant is flavor-dependent.** For correct alignment,
  `Δ_A + Δ_B = latency_A + latency_B` (each device's Δ contains the *partner's* playout
  latency). A **double main-peak alias** gives `(−500 + lat_A) + (+500 + lat_B)` — the
  *same sum*, so a sum-consistency check cannot catch it (`ca3013a2` would pass at 450 ms
  only because of the replica; a pure main-peak double alias is invisible to this check).
  A **double replica alias** shifts the sum by `2 × replica_lag ≈ 256 ms` — catchable.
  So: sum-consistency kills replica-flavor aliases; masking kills main-peak-flavor
  aliases; the overlap/spectral guards (A2) kill both. All three are needed.
- **A wide self-mask is unsafe, and a narrow one is insufficient.** With real offsets
  around −300…−420 ms the partner's beep can land ~100 ms after a self beep — right
  where the replica also lives. Masking must target *measured self-locked structure*
  (main peak + replicas found per device per trial), not a fixed window, and ambiguity
  between "partner arrival" and "self replica" must be resolved by the joint constraint
  and guards, not by masking alone.
- **The alias band overlaps the true-offset band** (aliased laptop offsets −290…−420 vs
  true offsets ~−300…−420). Therefore no offset-domain window — including A3's timing
  prior — can *structurally* exclude aliases. Priors shrink the search; they don't
  replace the guards.

## 2. Workstream A — kill the alias

Ordered so A0–A2 work on *existing* recordings; A3 needs client changes.

### A0. Root-cause the +128 ms self-replica (first, before freezing any mask design)

A discrete, self-grid-locked arrival ~128 ms after the detected self peak, similar lag
on both a MacBook and an Android phone, present in `ca3013a2` (6–12 kHz band).
Candidates, with discriminating tests:

1. **OS/driver echo path or acoustic secondary path** — check lag stability across
   trials, devices, bands (does it scale with anything physical?); inspect the raw
   waveform (a real acoustic arrival has the chirp's time-frequency structure).
2. **ScriptProcessor chunk duplication / capture-graph artifact** — 4096 samples is
   85.3 ms at 48 kHz / 92.9 ms at 44.1 kHz; neither matches 128 ms exactly, but check
   duplication across chunk boundaries and whether the client's context.sampleRate vs
   the WAV header rate could stretch 92.9 → 128.
3. **Pass-1 mis-identification** — is the "+128 ms replica" actually the *main* playout
   event, with pass-1's first-candidate-above-threshold rule (alignment.py:144-148)
   latching a weaker precursor at +82? (Verification measured the +128 event *larger*
   than the detected peak — consistent with this hypothesis.) If so, true playout
   latency is ~210 ms and the tight self window (−20/+230 ms, feature_extraction.py:166)
   barely contains it — window and τ1 policy both need revisiting.

Deliverable: a short `docs/replica-findings.md` with the mechanism, its parameters
(lag distribution, amplitude ratio, band dependence), and the decision it implies for
A1's mask and the sim's replica knob (B4). Survey *all* archived WAVs, not just
`ca3013a2` — the analysis is offline and cheap.

### A1. Fix the latent crash; mask self-locked structure through the WHOLE pipeline

1. **Fix `feature_extraction.py:204-212`**: the fallback `PeriodSelection` uses kwargs
   `chirp_start_sample=…`; the dataclass fields (alignment.py:37-44) are `chirp_start`
   etc. This unblocks the `cross_offset_ms is None` rejection path.
2. **Build a per-device self-structure mask.** From pass-1 self detections, find *all*
   envelope peaks phase-coherent with the self grid (mod 1000 ms) above a noise-floor
   multiple — main peak, replica(s), strong echo-tail bumps — and mask a narrow window
   around each (template length + small pad). The mask is *measured*, not assumed; its
   parameters land in `pipeline_constants.py` with units.
3. **Mask the sweep** (`_estimate_cross_device_offset_ms`): score offsets on the masked
   envelope; skip masked predictions instead of averaging zeros; require ≥ 10 of 20
   unmasked predictions for eligibility; keep the peakiness gate (on masked scores it
   becomes meaningful instead of trivially satisfied).
4. **Mask pass-3 per-beep selection too** (review blocker: without this, per-beep cross
   selection re-aliases even under a correct sweep offset, and the A2.1 guard would then
   reject *correctly-aligned* trials). Thread exclusion regions through
   `select_periods_for_beep`/`select_periods` (new parameter), and change the cross-beep
   τ1 policy from "first candidate above 0.30 × window-local max" to "strongest unmasked
   candidate" — the local max inside a ±200 ms cross window is otherwise the self beep.
5. **Joint cross-device selection.** Choose the pair `(Δ_A, Δ_B)` maximizing combined
   masked sweep score subject to `Δ_A + Δ_B ≈ self_off_A + self_off_B (± ~100 ms)` —
   both terms measured per trial. This kills replica-flavor double aliases (§1.2) and
   single-sided aliases; masking covers the main-peak flavor the constraint can't see.
   Requires the server to align both devices *together* rather than independently
   (signature change in `extract_recording_spectra` or a new joint-alignment step).
6. **Re-score the archive** (all 24 `paper_repro` trials) with A0–A1 in place and write
   the before/after table into `docs/`. Expected outcomes are *hypotheses to check, not
   pins*: `ca3013a2`-class trials must stop producing ACCEPT via alias (reject or
   collapse); correctly-aligned trials should keep plausible scores. **Caveat from
   review:** `fedbaf73`/`361d4526` are 14–15 kHz-band trials, and the pipeline currently
   hard-codes its bandpass from *current-band module constants*
   (alignment.py:32-33 derive from challenge_generator's 6–12 kHz values) — re-scoring
   them requires derive-from-`beep_spec` plumbing first (D3.5). Until then, the archive
   table covers the 6–12 kHz trials only.

### A2. Hard validity guards (make aliasing loud, never silent)

Guards in `validity.py::assess_capture_validity` (which today *rewards* aliasing —
aliased channels have perfect `ok_ratio` and high peaks). Plumbing prerequisite: add
`chirp_start` (samples) and `canonical_sample_rate` to `_summarize_per_beep`
(server.py:534-547) and the logged `per_beep_summary` — bump the log schema version.
Archive re-scores recompute summaries from WAVs (old logs lack these fields).

1. **Self-structure overlap guard (decisive):** any cross-beep `chirp_start` within
   ±15 ms of *any masked self-structure position* (main peaks AND replicas, not just
   detected self chirps) ⇒ count it; > 2 overlaps ⇒ `capture_valid=False`, reason
   `cross_selection_self_aliased`. This alone flags `ca3013a2` 20/20.
2. **Self-grid coherence test** (replaces v1's mis-specified `|Δ mod 500| < 60`): the
   danger zone is relative to the self grid, so test the circular distance of
   `(Δ_dev − self_offset_ms) mod 500` against the *measured self-locked lag set*
   (0 and replica lags). Equivalent direct form: does the envelope sampled at the chosen
   offset's predicted positions correlate better with the device's own emission grid
   than with an interpolated partner grid? Flag ⇒ reject unless the masked sweep score
   independently clears a high bar.
3. **Cross-channel spectral self-similarity (new, catches what amplitude checks miss):**
   Pearson between the device's cross-channel echo signature and *its own* self-channel
   echo signature. An aliased cross channel re-measures the same physical echo ⇒
   near-perfect correlation regardless of amplitude. High similarity + any grid-coherence
   flag ⇒ reject.
4. **Cross/self energy plausibility — warn-only** (v1 had it as a flag; review showed it
   both misses replica aliases at ~10% amplitude and false-positives the paper's primary
   scenario, where the enrolled phone sits *beside* the login device and cross ≈ self is
   legitimate). Log it; never gate on it.
5. **Sum-consistency check:** `Δ_A + Δ_B` vs measured `self_off_A + self_off_B`.
   Deviation ≈ 2 × replica lag ⇒ replica alias; large deviation ⇒ single-sided alias.
   Cannot catch double main-peak aliases (§1.2) — supporting evidence only.
6. **Deaf vs ambiguous (new):** distinct failure reasons —
   `partner_inaudible` (masked sweep max below the masked noise floor: the dominant
   *expected* live outcome post-fix given the known hardware asymmetry, e.g.
   `c175938d`-class trials) vs `cross_offset_ambiguous` (above floor but fails the
   peakiness gate or the joint constraint). Forensics must separate hardware failure
   from algorithm failure; phase 4 policy depends on it (§6).
7. **AEC / OS voice-processing guard (new):** granted `echoCancellation` or
   `voiceIsolation` true ⇒ `capture_valid=False` (today validity.py:53-62 only *warns*
   and never reads `voiceIsolation`, though it is present in every logged
   `granted_track_settings`); settings absent/unreported ⇒ explicit warning. Because
   OS-level processing is invisible to `getSettings()`, add an acoustic fingerprint:
   self echo-period energy collapsed relative to self chirp peak ⇒ warn
   `possible_aec_suppression`. (Browser AEC destroys the echo period at the source —
   README has said so all along; nothing enforced it.)
8. **Use `cross_offset_score`:** feature_extraction returns it; validity never reads
   it. Floor it relative to the masked noise floor (never absolute units, D3).

All failure reasons flow to the UI (§C2) — today `trial_result` carries
`measurement_failure_reasons` and the client renders none of them.

### A3. Timing priors (useful bound, NOT a structural kill — demoted in review)

v1 claimed a time-probe prior ± 150 ms "cannot contain the ±500 ms alias". Review
refuted this two ways: (a) the alias-offset band *overlaps* the true-offset band
(§1.2), so no window around the truth excludes aliases; (b) the error budget omitted
playout latency — the largest term (~100–200 ms), for which browser-reported values are
garbage (logged `output_latency`: 38.047 on one device vs 0.02 on another — units are
inconsistent across browsers/platforms; measured self offsets exceed reported
base+output latency by 44–80 ms), plus ScriptProcessor sample-0 quantization (4096
samples ≈ 85 ms). What A3 *does* buy: it bounds gross clock skew (kills the far/1000 ms
alias family and wild sweeps), shrinks the search so guards fire rarely, and gives
per-trial ground truth for forensics.

1. **Upload `record_start_audio_time`** (captured at app.js:308, currently not
   uploaded — one line). Server converts each self beep's `scheduled_audio_time` to an
   exact *scheduled* sample; the *acoustic* position adds playout latency, estimated
   NOT from `context.outputLatency` but from the device's own pass-1 measured
   `self_offset_ms` (which is precisely scheduled-vs-acoustic lag in the anchored
   recording clock).
2. **Websocket time probe:** 5–10 `time_probe` round trips per device; min-RTT sample;
   `offset_vs_server = t_server − (t0+t1)/2`; upload `{offset_vs_server_ms, min_rtt_ms}`.
   Stamp the first `onaudioprocess` callback with a `(Date.now(), context.currentTime)`
   pair to pin WAV sample 0 to both clocks. Prior:
   `Δ_prior ≈ clock skew (probes) + partner's measured self_offset_ms`, window scaled by
   the *measured* per-trial uncertainty (RTT + anchoring terms), not a fixed ±150 ms.
3. **Dual-mode contract (review blocker):** prior-bounded sweep **iff** A3 metadata is
   present; A1 masked full sweep otherwise. `alignment_mode` recorded per trial and per
   golden expectation. Pre-A3 WAV compatibility is a *permanent* requirement — the
   golden tripwire (B5) depends on scoring old recordings forever.
4. Validity compares measured Δ against the prior when present (warn on disagreement;
   the guards, not the prior, decide rejection).

While in app.js: vendor the socket.io client locally (currently CDN — dies on an
offline LAN bench). Migrate to `AudioWorklet` only if the sample-0 stamping needs it.

## 3. Workstream B — make the simulation a trustworthy self-diagnosis loop

The sim (`simulation/`, pyroomacoustics image-source model) is architecturally right:
it renders the two WAVs a scene *would* produce and pushes them through the unmodified
production pipeline. It reproduces the live bug exactly (verified: adverse scene ⇒ both
devices 12/12 self-aliased, mirroring `ca3013a2`). It becomes the regression harness for
Workstream A — after its own credibility is repaired:

### B1. Repair the contaminated defaults (before trusting any sim number)

1. **Phone preset**: `clock_offset_ms + output_latency_ms = 320 + 180 = 500 ≡ 0 (mod
   interleave)` — maximal schedule collision as the *default*. Change to a
   non-degenerate value and add an explicit `colliding_clocks()` scenario so the
   degenerate case stays covered *on purpose*.
2. **Laptop mic directivity**: the ideal `Cardioid` rear null makes the laptop deaf to
   its own speaker — the *inverse* of reality (live self peaks > 150). Use a finite
   front-to-back-ratio pattern (review notes pyroomacoustics' `CardioidFamily` supports
   this directly), ε calibrated against live self/cross peak ratios from the archive.
3. **Re-validate**: regenerate the README validation table; until then the old numbers
   and the "min(c_a,c_b) separates best" recommendation carry a contamination
   disclaimer (added to `simulation/README.md` as part of this plan's tidy-up).

### B2. Ground-truth-aware verdicts (the sim's superpower — use it)

The sim knows exactly where every emission lands. Add to `scene.run_trial`:

- Per beep, classify each pipeline selection as `SELF` / `PARTNER` / `NOISE` by distance
  to ground-truth arrival instants (promote the review's triple-render technique —
  full / partner-muted / self-muted — into `scene.py`; the render path already supports
  per-source muting cleanly).
- Report `alias_count`, `swap_count` (self search grabbing partner), selection timing
  errors, and true-vs-estimated Δ per device.
- **Wire `assess_capture_validity` into `run_trial`** with server-equivalent summaries
  (review found the sim never calls validity at all, so reject-reason assertions could
  not run in-sim as v1 scoped them).
- **Compensation ground truth (new):** the sim knows both mics' true responses, so
  assert `compensation ≈ true M_B/M_A` on the chirp grid — the only place the
  compensation math is directly checkable (see D3.6 for why this matters).
- `smoke_test.py` asserts **zero aliased/swapped selections** in every scenario *in
  addition to* score separation (today it counts `selection_ok`, which is true for
  aliased picks — it literally cannot fail on this bug).

### B3. Alias regression scenarios (the bug, pinned forever)

- `adverse_alias()`: adverse orientation + BA attenuated ×0.01 + clock offsets near the
  danger zone. Assert: fixed pipeline either aligns correctly (Δ error < 50 ms) or
  rejects with `cross_selection_self_aliased` — never an ACCEPT via aliased selections.
- `replica_alias()` (new, pending A0): inject a self-replica (lag/amplitude per A0's
  findings) and assert the guards catch the replica flavor specifically.
- `deaf_laptop()`: one-sided deafness — assert `partner_inaudible` (not `…aliased`,
  not a crash) on the deaf side and single-sided-alias detection (A2.5).
- `colliding_clocks()`: the degenerate 500 ms preset, deliberately.

### B4. Close the realism gaps (priority order, each a scenario knob)

1. **AEC model** (top gap): adaptive suppression of the known playback reference —
   pairs with the A2.7 live guard.
2. **Self-replica knob** — whatever mechanism A0 identifies, parameterized.
3. **Per-beep playout-latency jitter** (± several ms) — stresses the median-based
   `self_offset_ms` and the tight windows, currently never exercised.
4. **44.1 kHz capture path** — render at 44.1 k and let `canonicalize_audio` resample,
   as real Macs do (sim currently hard-asserts 48 k end-to-end). Note this also
   exercises `compensation._stack_spectra`'s silent drop of grid-size-mismatched beeps
   (D3.6).
5. Time-varying AGC (attack/release), colored noise, speaker distortion at touch.

### B5. The self-diagnosis loop (how changes get validated from now on)

Add `simulation/regression.py` (single entry point, exit-code semantics) that runs:

1. Sim scenario suite with ground-truth verdicts (B2/B3) — catches selection bugs.
2. **Golden-file re-score** of pinned archive WAVs — catches drift. Review corrections
   applied: goldens are pinned **after Phase 0 lands** (v1 pinned pre-fix scores that
   Phase 0 itself would move); pins are primarily **structural facts** — selection
   positions, chosen Δ, alias counts, `alignment_mode`, failure reasons — plus a score
   band whose tolerance is *derived empirically* (re-score the archive twice around a
   no-op change), not asserted at ±0.02. Golden set: `ca3013a2`
   (`cross_selection_self_aliased`), a correctly-aligned 6–12 kHz trial, `c175938d`
   (`partner_inaudible` — the deaf golden), `b1f00218` (clipping — expectation set
   deliberately per D3.7). 14–15 kHz goldens (`fedbaf73`, `361d4526`) join once D3.5
   makes the pipeline band-parametric. Re-pins are *scheduled* at each phase boundary
   (each phase intentionally moves behavior) — a tripwire that fires on every planned
   change is an alarm nobody reads.
3. Print a one-screen diff table (per scenario/golden: score, Δ error, alias counts,
   verdict + reason).

Enforcement (review: honor-system isn't a mechanism, and the tree currently has zero
commits): commit the repo at the start of Phase 1 (D4's `.gitignore` is already in
place), then wire `regression.py` into `run.sh`/a pre-commit hook, and have `server.py`
stamp the last-green regression run into each trial record so uncovered live trials are
visible in the log.

## 4. Workstream C — live-trial forensics & UX

### C1. Per-trial diagnostic report

Extend `analysis/inspect_trial.py` (fix its broken `--raw` argv handling) with
`--plot <trial_id>` producing one PNG/HTML per device:

- matched-filter envelope with self/cross selections, the **self-structure mask**
  (main peaks + replicas), and the schedule grid overlaid;
- the offset sweep score curve (masked and raw-diagnostic) with chosen Δ, prior window
  when present, and self-grid danger lags marked;
- per-direction averaged spectra (AA/AB/BA/BB) before/after compensation, plus the
  A2.3 self-similarity value;
- the validity verdict with reasons.

Acceptance: a failed live trial is diagnosable from the report alone, without touching
raw WAVs. (This is what took multiple sessions to discover by hand.)

### C2. Surface verdict reasons in the browser

`trial_result` already carries `capture_valid`, `measurement_failure_reasons`,
`measurement_warnings`; render them (app.js:652-668). "Withheld" without a reason cost
us weeks. Also fix the stuck-trial deadlock: on peer disconnect mid-trial, server must
emit `trial_error` so the surviving client resets (`isBusy` latch, app.js:604/638).

### C3. Version stamping

Stamp every trial record with `pipeline_version` (bump on any behavior change), the
constants snapshot (D3), `alignment_mode` (A3.3), and the regression stamp (B5).
`feature_version`/`classifier_version` exist but were never bumped on retunes — which is
exactly how the log became uninterpretable.

## 5. Workstream D — data & constants hygiene

### D1. Split the trial log by generation — **done 2026-07-07**

13 legacy records (7 `linear_chirp_v1` + 6 `reciprocal_linear_chirp_v1` by
`challenge_family`; the same 13 are 10 `phase2_v1` + 3 `phase2_v2` by
`feature_version` — two taxonomies, don't conflate them) moved to
`data/archive/logs/trials-legacy.jsonl`; `data/logs/trials.jsonl` now contains only the
24 `paper_repro` trials. Remaining: analysis scripts gain a `--feature-version` filter
with the current generation as default.

### D2. Fix or delete stale analysis scripts

- `analysis/fit_logistic.py` — **delete** (its feature schema matches zero generations;
  it can never have worked against this log).
- `analysis/smoke_test.py` — **delete** (crashes on the feature_extraction kwargs bug;
  strictly superseded by `simulation/smoke_test.py`).
- `analysis/sweep_thresholds.py` — **rewrite**: read `record["score"]["score"]` +
  `record["pair"]` with the generation filter and an explicit policy for the 14 early
  paper_repro records that predate validity wiring (no `pair` at all). (Correction from
  review: as-is it exits loudly with zero rows — `pair.score` never existed in *any*
  generation — so it's dead, not silently wrong.)
- `analysis/summarize_trials.py` — drop the legacy compat shims (post-D1); group by
  condition *within* a generation.
- Dead code: `feature_extraction._find_global_peaks` (+ its stale docstring),
  `trial_logger.read_trials`, `scoring.score_mode="max"`, unused `playBeep()`/
  `peerRoles` in app.js. (Verified: zero dangling imports.)

### D3. Constants & numerics: one module, explicit units, no absolute thresholds

The audit found **24 hand-tuned constants** across 7 files; three are in absolute
matched-filter-envelope units (`chirp_peak_value < 1.0` feature_extraction.py:176,
`MIN_MEDIAN_CHIRP_PEAK = 0.02` validity.py:15, the sweep's implicit scale) — these
silently change meaning whenever `BEEP_AMPLITUDE`, mic gain, band, or template length
moves. This is why re-scoring the same WAVs across sessions gave different numbers.

1. Consolidate all tunables into `pipeline_constants.py` with units and rationale —
   **including every new A1/A2 threshold introduced by this plan** (mask pads, ±15 ms
   overlap, sum tolerance, coherence zones, ≥10-of-20 counts): no new unhomed magic
   numbers.
2. Replace absolute-envelope thresholds with normalized ones (relative to
   per-recording noise floor or self-peak median).
3. Name the inline `0.02 * env_max` echo-threshold floor (alignment.py:169).
4. `SMOOTH_WINDOW_FREQ_POINTS = 20` (scoring.py:19) is a boxcar in FFT **bins**, so its
   bandwidth in Hz silently changes with echo-segment duration — re-denominate in Hz,
   convert to bins at runtime. (Directly relevant to phase 4's band comparison: the two
   band configs used different chirp durations historically.)
5. **Band-parametric pipeline:** derive bandpass edges and spectrum band from the
   trial's `beep_spec`, not module-level constants of the current band
   (alignment.py:32-33) — prerequisite for re-scoring the 14–15 kHz archive and for
   phase 4's band decision.
6. **compensation.py (absent from v1 — review flagged it):** replace
   `CubicSpline(..., extrapolate=True)` (compensation.py:74) with a shape-preserving
   interpolator (PCHIP) and forbid extrapolation (restrict signatures to the grid
   overlap); log the count of beeps `_stack_spectra` silently drops on grid-size
   mismatch (compensation.py:63-65) into validity. Compensation is the suspected cause
   of the documented c_a/c_b asymmetry (progress report blocker #3) and is directly
   verifiable in-sim (B2).
7. **clipping.py:** replace the single-sample trip (`clipped_sample_count > 0` ⇒
   trial-fatal via validity.py:101-104) with a fraction+duration threshold and per-beep
   localization — clipping confined to self direct-path chirps need not invalidate cross
   echo periods. Without this, phase 4's *touch* condition (the paper's primary
   scenario, and the most clip-prone) may be systematically uncollectable.

### D4. Directory tidy-up — **done 2026-07-07**

- Archived: 26 legacy-generation WAVs + 2 orphan WAVs (≈11 MB) → `data/archive/audio/`;
  13 legacy log records → `data/archive/logs/trials-legacy.jsonl`.
- Added `research/proximity-echo/.gitignore` (`.venv/`, `__pycache__/`, `data/audio/`,
  `data/archive/`, `.claude/settings.local.json`); `data/logs/trials.jsonl` stays
  tracked. `__pycache__` trees deleted.
- `progress-report-proximity.md` moved → `docs/`, with a **correction banner** (review:
  the moved report still presented alias-invalidated results as the project record —
  the 0.86 touch ACCEPT is `ca3013a2`, now proven self-aliased; the results table's
  scores disagree with the log for the same trials, e.g. `fedbaf73` 0.862 reported vs
  0.464 logged; the "analysis pipeline is no longer the bottleneck" conclusion is
  unsupported). Same disclaimer added to `simulation/README.md` pending B1.3.
- Everything else kept (all core modules, simulation, analysis, static/templates, data).
  Stale-script deletions happen in D2 (they are code changes, reviewed like the rest).

## 6. Workstream E — hardware reality & experiment design (was buried in phase 4)

Post-fix, the *expected* live outcome is honest `partner_inaudible` rejections — the
MacBook's beamformed mic is the real bottleneck the alias was hiding. v1 under-planned
this (review: "if the link test never reaches 0.5 both ways, phase 4's gate defaults to
no-go with nothing left to try").

1. **Hardware fallback ladder**, each tier entered via the same link-test gate
   (≥ 0.5 both directions on the live meter):
   T1 fixed orientation (phone bottom-edge speaker aimed at the laptop mic);
   T2 band drop to 4–9 kHz (more omnidirectional speaker output);
   T3 external USB mic on the laptop (bypasses beamforming);
   T4 alternate phone.
   The browser-MVP go/no-go is *per tier* — "works only with an external mic" is a
   valid, reportable outcome.
2. **Experiment design with power:** collect until ≥ N *valid* trials per condition
   (rejected trials are re-collected, never counted), N chosen so a bootstrap CI on the
   touch-vs-1m score separation excludes zero — not a point-EER from 5 samples. Deaf
   and AEC rejections are logged per tier (they are data about the tier, not noise).
3. Threshold work happens only on this clean data; the paper's 0.78 was tuned on their
   hardware and their correctly-aligned channels. Band decision (6–12 vs 14–15 kHz) by
   *separation*, not absolute score, using the band-parametric pipeline (D3.5).

## 7. Sequencing

| Phase | Contents | Gate to next phase |
|---|---|---|
| 0 (1–2 days) | A0 replica root-cause; A1 (crash fix, structure mask through sweep + pass-3, joint selection); A2.1 guard + summary-schema plumbing; archive re-score table (6–12 kHz trials) | Aliased trials rejected, aligned trials preserved, replica mechanism documented |
| 1 (~1 day) | First commit of the tree; B1 preset repair; B2 ground-truth verdicts + validity wiring; B3 alias scenarios; B5 `regression.py` + post-Phase-0 goldens + enforcement hook | `regression.py` green and enforced; sim README re-validated |
| 2 (2–3 days) | A3 timing (client+server, dual-mode); A2.2–A2.8 remaining guards; C2 UI reasons + deadlock fix; D3.7 clipping rework | Live trial logs show prior-vs-measured Δ agreement; guards fire correctly on deliberate misconfigurations |
| 3 (~1 day) | C1 diagnostic plots; C3 version stamping; D2, D3.1–D3.6 | A failed live trial diagnosed from its report alone; goldens re-pinned |
| 4 (research) | Workstream E: tier ladder + powered distance sweep + threshold/band analysis | Go/no-go per hardware tier; then attack scenarios (sim first: AEC + relay scenes) |

## 8. Acceptance criteria (definition of done for the fix)

- [ ] `ca3013a2` re-scored ⇒ `capture_valid=False`, reason `cross_selection_self_aliased` (via the A2 guards; A1 alone is *not* sufficient — review demonstrated the masked sweep still aliases onto the replica until A0's findings shape the mask).
- [ ] `c175938d` re-scored ⇒ `partner_inaudible` (deaf, not aliased, not a crash).
- [ ] A correctly-aligned 6–12 kHz archive trial keeps a stable score across two consecutive re-scores (tolerance set empirically, then pinned).
- [ ] The replica mechanism is identified and written up (`docs/replica-findings.md`), and the sim reproduces it via a knob.
- [ ] Sim: zero aliased **and** zero swapped selections (ground-truth classified) across the scenario suite; `adverse_alias()`/`replica_alias()` reject or align correctly; `deaf_laptop()` yields `partner_inaudible`.
- [ ] A deliberately AEC-on live trial is rejected with the AEC reason surfaced in the browser.
- [ ] Live trial with A3 metadata: measured Δ consistent with the prior; `alignment_mode` logged; pre-A3 WAVs still score (dual-mode).
- [ ] `regression.py` exits 0, is wired into `run.sh`/pre-commit, and the tree is committed.
- [ ] A deliberately mis-configured live trial (phone face-down) produces a diagnostic report that names the failure without WAV inspection.

## 9. File-by-file change map

| File | Changes |
|---|---|
| `feature_extraction.py` | A1.1 kwargs fix; self-structure mask build; masked sweep; joint selection; delete `_find_global_peaks`; fix stale docstring; return mask + sweep curves for diagnostics |
| `alignment.py` | exclusion-regions parameter through `select_periods_for_beep`/`select_periods`; cross-beep τ1 = strongest unmasked candidate; band-parametric bandpass (D3.5); name the inline `0.02*env_max` |
| `validity.py` | A2 guards 1–8 (incl. deaf/ambiguous split, AEC+voiceIsolation, spectral self-similarity); normalized thresholds |
| `server.py` | `time_probe` handler; joint alignment call; `_summarize_per_beep` +`chirp_start`+rate (schema bump); peer-disconnect `trial_error`; version/regression stamping |
| `static/app.js` | upload `record_start_audio_time`; time probe; first-callback stamp; render failure reasons; remove `playBeep`/`peerRoles`; vendor socket.io |
| `scoring.py` | drop dead `score_mode="max"`; `SMOOTH_WINDOW` in Hz; constants move |
| `compensation.py` | PCHIP, no extrapolation, dropped-beep counts into validity (D3.6) |
| `clipping.py` | fraction+duration threshold, per-beep localization (D3.7) |
| `simulation/scene.py` | B1 presets + finite-F/B directivity; B2 ground-truth classification (triple render); validity wiring; compensation ground-truth check |
| `simulation/scenarios.py` | `adverse_alias()`, `replica_alias()`, `deaf_laptop()`, `colliding_clocks()` |
| `simulation/smoke_test.py` | assert zero alias/swap + separation |
| `simulation/regression.py` | new — B5 entry point |
| `analysis/golden.json` | new — structural pins + empirical score bands, `alignment_mode` per golden |
| `analysis/inspect_trial.py` | `--plot` report; fix `--raw` |
| `analysis/{fit_logistic,smoke_test}.py` | delete |
| `analysis/sweep_thresholds.py` | rewrite for current schema + generation filter + pre-validity-record policy |
| `pipeline_constants.py` | new — D3, including all new A1/A2 thresholds |
| `docs/replica-findings.md` | new — A0 deliverable |

## 10. Reference: evidence trail

- Empirical alias verification (2026-07-06): re-extraction of `ca3013a2` WAVs — 20/20
  and 15/15 cross selections at self positions.
- Four audit reports (2026-07-07): simulation, aux modules, browser client, inventory.
- Adversarial review (2026-07-07, three lenses): produced the replica discovery
  (mask-as-v1-specified re-ran on `ca3013a2` and still aliased), the pass-3 re-selection
  blocker, the A3 demotion, the guard corrections (A2.2 formula, A2.3 flip to warn-only),
  the golden re-design, the dual-mode contract, and the deaf/AEC/hardware/compensation/
  clipping omissions — all folded into this v2.
- Replica independently re-verified on `ca3013a2` envelopes before adopting the v2
  design: discrete self-grid-locked arrival at +128 ms on both devices, amplitude
  comparable to or exceeding the detected self peak.
