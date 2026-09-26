# shrink: how small can option A get?

Re-scores the real fieldtest recordings (18 sessions, JB and N1s probes) under receiver simplifications that make the circuit smaller, and checks that 30 cm vs 100 cm still separate. Reuses `melody/fieldtest/fieldanalysis.py` and `fieldprobes.py` (imported, never edited). Nothing is written into the session folders.

Run with `PY=../../../../proximity-echo/.venv/bin/python3` from this folder.

| script | tests | output |
| --- | --- | --- |
| `receiver_variants.py` | N1s: short slices, 1-/3-bit quantizing, baseband decimation, no ppm bank, stacks of these; score loss, margin, flight error, decision flips; self-arrival late-claim budget | `out_receiver_variants.txt` |
| `first_crossing.py` | circuit-friendly arrival = earliest lag with score ≥ k·T (no local-max logic) | `out_first_crossing.txt` |
| `bits_baseband.py` | 2-/3-bit recording vs 1-bit, dither, relaxed first-peak check | `out_bits_baseband.txt` |
| `cost_model.py` | R1CS / Plonkish constraint estimates per ranging round for each variant (unit costs from the `../v1-bn254` fit) | stdout |
| `rescore.py` | full grid: every single knob (`--list`) and lean stacks, both probes, all sessions, fixed T, realistic windows | `out/rescore_<tag>.json`, `logs/out_<tag>.log` |

`out/raw_*.pkl` are rescore caches (`--reuse`), `out/summary.log` is the long table; both gitignored. `out/ref_*.json` are the baseline arrivals/flights.

## Key results (details: `../../../../2026-09-26-zk-gap-research.md` §4)

- Credible stack, about 6,800× below naive A: per-round PRF QPSK chips (1 s at 8 kchip/s), 16 k complex baseband + notch, then 1-bit; fixed T instead of 64 nulls; no ppm bank; earliest-crossing rule; self window ±1–2 ms from native OS timestamps, cross dense ±10 ms. **~1.1M R1CS per round, ~0.53M per phone** (estimate from the cost model). Decisions 15/0/0 on both probes; margin min 2.1 dB (JB), 5.9 dB (N1s); NEAR max 34 cm, FAR min 101.5 cm.
- 0 ppm (no bank) cost nothing: flight error ≤ 2.1 cm.
- Doesn't work: 250 ms code (margin 0.0–0.4 dB under realistic windows); 1-bit capture without the notch (JB loses 24/144 arrivals); web timing prior (`win5exp`: 144/144 arrivals lost).
- Even small, A adds no security: the prover still supplies the recording.
