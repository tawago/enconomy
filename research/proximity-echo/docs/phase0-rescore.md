# Phase-0 re-score of the trial archive (fix-plan A1.6 — acceptance run)

Generated 2026-07-07 by the re-score agent, offline from the archived WAVs, with the
Phase-0 pipeline (`feature_version = paper_repro_v2`: joint train assignment, sum
identity with `MAX_ROUND_TRIP_MS = 25`, self-structure masking, A2.1/A2.5 guards):

```
.venv/bin/python analysis/rescore_archive.py
```

- "Old" values come from `data/logs/trials.jsonl` (log schema 1, pre-fix pipeline);
  old code was NOT re-run. Old records did not log per-device Δ before `ffeb620f`
  (shown as `—`), and never logged failure reasons.
- Scope: the 19 6–12 kHz trials; the 5 14–15 kHz trials are explicitly SKIPPED
  (pipeline band-locked until fix-plan D3.5).
- Two consecutive full runs are byte-identical (determinism verified this session).
- No trial raised an exception; the harness's per-trial ERROR path never fired.

## Per-trial results

Δ = cross offset per device, ms. "self lat A/B" = assigned self playout latency per
device from the train assignment (ms). "alias A/B" = A2.1 alias-overlap counts
(guard fires at >2). Verdicts: WITHHELD = capture invalid, raw score kept for
forensics; the raw ACCEPT threshold is 0.78.

| trial | cond | Δ_A old → new [src] | Δ_B old → new [src] | self lat A/B (assignment) | alias A/B | old score (verdict) | new score (verdict) → failure reasons | NOTES |
|---|---|---|---|---|---|---|---|---|
| d4624efe | — | — → −358.2 [train] | — → −251.3 [train] | 119.8 / 270.2 (joint, rt 0.51 ms) | 0 / 0 | 0.055 (REJECT) | −0.074 (REJECT) | Replica-findings §3/§6 unresolved 22 ms echo-vs-partner trial: assignment took the 22 ms secondary as partner; `sweep_train_disagreement` on both devices (sweep −410/+720 vs train −358.2/−251.3≡+748.7); `cross_partner_in_self_tail` on A. Warn-only. |
| bbcb9f47 | — | — → −406.8 [train] | — → −232.6 [train] | 209.8 / 150.9 (joint, rt −0.19 ms) | 0 / 0 | 0.330 (REJECT) | 0.479 (WITHHELD) → device_a_clipped | Possible mirror-swap: chosen Mac self 209.8 ms is outside the 60–150 ms Mac prior (`self_latency_outside_prior` warned) and replica-findings §3 lists 209.8 as a Mac-side partner-capture; the mirror labeling (93.2/267.4) also satisfies the sum identity (≈+0.1 ms) and fits both priors. Withheld via clipping either way. |
| 0b8127ea | — | — → −307.1 [train] | — → −341.8 [train] | 92.2 / 258.8 (joint, rt 0.12 ms) | 0 / 0 | −0.012 (REJECT) | 0.356 (WITHHELD) → AB/BA_low_period_recovery, device_a_clipped | The 192.9 ms Mac-side partner-capture case in §3 is now correctly labeled partner. |
| b1f00218 | — | — → −342.9 [train] | — → −302.2 [train] | 91.0 / 263.6 (joint, rt 0.23 ms) | 0 / 0 | −0.011 (REJECT) | 0.524 (WITHHELD) → BA_low_period_recovery, device_a_clipped | §3's 157.1 ms partner-capture correctly labeled partner; `cross_partner_in_self_tail` on A (warn-only, 66 ms gap). |
| 8e25f1d4 | 30cm | — → −269.9 [train] | — → −299.3 [train] | 122.8 / 306.0 (joint, rt 2.06 ms) | 0 / 0 | −0.163 (REJECT) | −0.172 (REJECT) | Round trip 2.06 ms ≈ 0.35 m — consistent with 30 cm. Android self 306 ms = §3's max observed latency. |
| fce29eae | — | — → +421.2 [train] | — → −66.6 [train] | 91.3 / 263.7 (joint, rt −0.30 ms) | 0 / 0 | 0.131 (REJECT) | 0.581 (WITHHELD) → AA/AB/BA_low_period_recovery, device_a_clipped | Δ_A reported on the positive mod-1000 branch (sweep prints −580 ≡ +420); consumers must compare mod period. |
| d7b1223a | — | — → −265.0 [train] | — → −386.3 [train] | 93.0 / 254.9 (joint, rt 0.76 ms) | 0 / 0 | 0.080 (REJECT) | −0.171 (REJECT) | Clean. |
| 638d1fbc | — | — → −267.4 [train] | — → −330.9 [train] | 121.0 / 280.3 (joint, rt 0.34 ms) | 0 / 1 | −0.288 (REJECT) | 0.400 (WITHHELD) → BA_low_period_recovery, device_a_clipped | Only nonzero alias-overlap count archive-wide (1, below the >2 threshold); `train_assignment_ambiguous` warned on both devices. |
| ffeb620f | — | −280.0 → −276.5 [train] | −360.0 → −358.3 [train] | 92.7 / 272.4 (joint, rt 0.08 ms) | 0 / 0 | 0.043 (REJECT) | 0.258 (WITHHELD) → device_a_clipped | **Preservation reference (§8):** re-aligns within 3.5 ms of logged offsets, now sub-ms train precision; §3's 223.5 ms Mac argmax case correctly labeled partner. Device_b trains at 12/20 support. |
| ca3013a2 | — | −290.0 → −288.5 [train] | **+740.0 → −385.3** [train] | 82.0 / 243.7 (joint, rt 0.47 ms) | 0 / 0 | **0.866 (ACCEPT)** | 0.277 (WITHHELD) → AB/BA/BB_low_period_recovery | **The aliased-ACCEPT trial (gate a): laptop Δ retained (≈−288), phone alias +740 corrected to ≈−385 by the joint assignment; no ACCEPT survives.** c_b collapses 0.75→0.00 once the phone channel scores the true partner signal. |
| 45a34992 | 30cm | −390.0 → −250.2 [train] | +790.0 → −345.3 [train] | 109.2 / 292.2 (joint, rt 3.12 ms) | 0 / 0 | 0.000 (WITHHELD raw REJECT) | −0.021 (WITHHELD) → BB_low_period_recovery | Same session as ca3013a2; phone alias corrected. rt 3.12 ms ≈ 0.54 m (30 cm condition + geometry slack). |
| 2e7904fa | 1m | −420.0 → −243.2 [train] | +760.0 → −406.2 [train] | 82.5 / 261.5 (joint, rt 6.54 ms) | 0 / 0 | 0.048 (WITHHELD raw REJECT) | 0.714 (WITHHELD) → BB_low_period_recovery | rt 6.54 ms ≈ 1.12 m — matches the 1 m condition (the F1 `MAX_ROUND_TRIP_MS` fix); raw score jumps to 0.714 (< 0.78, and withheld regardless). `sweep_train_disagreement` on B (warn-only). |
| e45a9b51 | touch | −420.0 → −316.8 [train] | +640.0 → −357.6 [train] | 82.5 / 242.8 (joint, rt 0.32 ms) | 0 / 0 | 0.184 (REJECT, was capture-valid) | 0.000 (WITHHELD) → AB/BA/BB_low_period_recovery | Phone alias corrected; touch-distance rt ≈ 0. Was capture-valid pre-fix only because the aliased channel self-correlated. |
| 1703c871 | touch2 | −400.0 → −400.0 [sweep] | +730.0 → +720.0 [sweep] | 82.5 / 238.2·unlocked (partial) | 0 / 0 | **0.825 (WITHHELD raw ACCEPT)** | −0.002 (WITHHELD) → AA/AB/BA/BB_low_period_recovery, device_a_self_train_ambiguous | §3's minimum-gap trial (17.1 ms): partner sits in the self tail; A warns `self_train_ambiguous` + `unassigned_train_in_self_tail` (F3 mask trim recovers true −400), B fails self-lock (σ 1.66 ms, amp 1.8). Raw-ACCEPT alias is gone. Sum residual −0.77 ms. |
| d6415a40 | touch3 | −390.0 → −390.0 [sweep] | +770.0 → +840.0 [sweep] | 116.6 / 270.3 (partial) | 0 / 0 | 0.341 (WITHHELD raw REJECT) | 0.131 (WITHHELD) → BA/BB_low_period_recovery, **cross_offset_sum_inconsistent**, device_a_self_train_ambiguous | Deaf-class (android side inaudible per §3): no partner train either side; sweep offsets violate the sum identity by 63.0 ms >> 35 ms dual-sweep tolerance → loud A2.5 rejection. |
| b96aa35b | touch | −420.0 → −275.5 [train] | +610.0 → −388.0 [train] | 82.9 / 253.4 (joint, rt 0.16 ms) | 0 / 0 | 0.102 (REJECT, was capture-valid) | 0.000 (WITHHELD) → AA/AB/BA/BB_low_period_recovery | Phone alias corrected; rt ≈ 0 at touch. |
| 6351c0e0 | touch2 | −390.0 → −240.7 [train] | +660.0 → −343.9 [train] | 112.0 / 302.2 (joint, rt 1.20 ms) | 0 / 0 | −0.076 (WITHHELD raw REJECT) | −0.107 (WITHHELD) → AB/BA/BB_low_period_recovery | Clean correction. |
| ab4a9f21 | touch3 | −390.0 → −317.5 [train] | +730.0 → −271.9 [train] | 110.2 / 300.1 (joint, rt 0.22 ms) | 0 / 0 | −0.136 (WITHHELD raw REJECT) | 0.000 (WITHHELD) → AA/AB/BA/BB_low_period_recovery, device_a_clipped | `train_assignment_ambiguous` warned both devices (warn-only). |
| b933225d | — | +770.0 → −260.0 [sweep] | −420.0 → −350.0 [sweep] | 264.5 / 81.8 (partial) | 0 / 0 | 0.410 (WITHHELD raw REJECT) | 0.256 (WITHHELD) → AB_low_period_recovery, AB_weak_direct_path, BB_low_period_recovery, **cross_offset_sum_inconsistent**, device_b_clipped, device_b_self_train_ambiguous | Deaf-class both sides (§3): no partner trains; sweep offsets violate sum identity by 43.7 ms → loud A2.5 rejection, plus B `self_train_ambiguous`. Note: device_a here is the android. |

### Skipped trials (explicit, per harness output)

| trial | cond | reason |
|---|---|---|
| fadae387 | — | 14–15 kHz band; pipeline band-locked to 6–12 kHz (fix-plan D3.5 pending) |
| 361d4526 | — | 14–15 kHz band; pipeline band-locked to 6–12 kHz (fix-plan D3.5 pending) |
| c175938d | — | 14–15 kHz band; pipeline band-locked to 6–12 kHz (fix-plan D3.5 pending) |
| fedbaf73 | touch | 14–15 kHz band; pipeline band-locked to 6–12 kHz (fix-plan D3.5 pending) |
| 976bfc01 | — | 14–15 kHz band; pipeline band-locked to 6–12 kHz (fix-plan D3.5 pending) |

## Interpretation (keyed to replica-findings §3 expectations)

**Class changes and why:**

- **ca3013a2 (the alias):** the archive's only ACCEPT (0.866) becomes 0.277 WITHHELD.
  Exactly as replica-findings §4.1.6 predicted: the laptop channel's Δ was always true
  (−290 → −288.5, retained), and the phone channel's +740 was the self-latch alias,
  corrected to −385.3 by the joint assignment (sum residual 0.47 ms = touch-distance
  round trip). c_b drops 0.75 → 0.00 because the phone channel now scores the real,
  weak partner signal instead of the device's own loop.
- **The android-alias family** (45a34992, 2e7904fa, e45a9b51, b96aa35b, 6351c0e0,
  ab4a9f21, and raw-ACCEPT 1703c871): every phone-side Δ in the +610…+790 range —
  §3's pass-1 partner-capture on androids whose true latency (242–306 ms) exceeded the
  old +230 ms window — flips to a negative train-assigned offset satisfying the sum
  identity, or (1703c871) fails loudly. Round trips scale with condition: ≈0–0.3 ms at
  touch, 2.06/3.12 ms at 30 cm, 6.54 ms ≈ 1.1 m at 1 m (2e7904fa, recovered by the F1
  `MAX_ROUND_TRIP_MS = 25` cut; its raw score 0.714 is the strongest genuine cross
  signal in the archive, still below the 0.78 accept bar and withheld).
- **Mac-side argmax partner-captures** from §3 (ffeb620f 223.5, 0b8127ea 192.9,
  b1f00218 157.1) are all now labeled partner trains; ffeb620f is the §8 preservation
  reference and re-aligns within 3.5 ms of its logged Δs. bbcb9f47's 209.8 ms case is
  the one §3 entry the joint assignment resolved the *other* way (self = 209.8): the
  mirror labeling is sum-identity-degenerate to ±0.3 ms, priors favor the mirror, and
  the pipeline correctly warns `self_latency_outside_prior` — flagged for the D3/A3
  latency-prior work; the trial is withheld (clipping) regardless.
- **Deaf set** (b933225d both sides, d6415a40 android side — §3's inaudible class):
  degrade to partial assignment; the masked sweep still returns above-floor offsets
  (leakage/noise), so the literal `partner_inaudible` reason never fires — instead the
  A2.5 sum check catches them (residuals 43.7 / 63.0 ms >> the 35 ms dual-sweep
  tolerance) alongside `self_train_ambiguous`. Loud rejection, no exception, no accept.
- **Ambiguous set:** d4624efe keeps its 22 ms echo-vs-partner ambiguity (§3/§6): the
  joint assignment picks the secondary as partner with a plausible 0.51 ms round trip,
  but both devices warn `sweep_train_disagreement`; verdict REJECT, so nothing rides on
  it. d6415a40 and 2e7904fa resolved as above.
- **REJECT → WITHHELD migration (13/19 trials):** driven entirely by *pre-Phase-0*
  guards — `device_X_clipped` (8 trials; a WAV property independent of alignment, never
  logged under schema 1) and `*_low_period_recovery` (12 trials; the corrected
  alignment now scores the true, weak partner channel, so honest cross-channel
  weakness surfaces — inherited by fix-plan §E). No Phase-0 guard
  (`cross_selection_self_aliased`, `cross_offset_sum_inconsistent`,
  `self_train_ambiguous`, `partner_inaudible`) fired on any jointly-assigned trial;
  alias-overlap counts are 0 everywhere except 638d1fbc device_b (1, below threshold).

**Acceptance gate (fix-plan §7/§8 as amended by replica-findings §4.1.6): PASS.**
(a) no alias-driven ACCEPT survives, ca3013a2 laptop retained / phone corrected;
(b) aligned trials keep plausible sub-ms-consistent offsets and scores, zero Phase-0
guard misfires on aligned trials; (c) zero crashes across 24 records, deaf trials fail
loudly via the A2.5/self-train guards.
