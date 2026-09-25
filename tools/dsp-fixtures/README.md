# dsp-fixtures

Parity fixtures for the Kotlin JBL250 receiver (`app/composeApp/src/commonMain/kotlin/com/enconomy/pop/dsp`), contract `docs/pop-contract.md` §6 and §10.2.

```
research/proximity-echo/.venv/bin/python3 tools/dsp-fixtures/make_fixtures.py          # write
research/proximity-echo/.venv/bin/python3 tools/dsp-fixtures/make_fixtures.py --check  # diff only, exit 1 on change
```

Needs the field wavs under `research/sound-bound/spikes/melody/fieldtest/data/sessions` (gitignored, local only). Reads `fieldprobes.py` read-only for the field bed templates (PCG64, so Kotlin cannot regenerate them). ~6 s.

## Files

`dsp_ref.py`: Python reference of contract §6 (numpy + scipy `gumbel_r` for the bar). The Kotlin code mirrors it line by line. Expected values in the fixtures come from here, run on the exact bytes stored in the fixture (cropped int16 + float32 templates), so Kotlin parity is exact by construction. Contract §1 puts `dsp_ref.py` under `server/pop/`; that file did not exist when this was written, so the fixture reference lives here. If the server grows its own, diff the two with the fixtures.

Output in `app/composeApp/src/commonTest/resources/dsp/` (~4.5 MB total):

| File | What |
| --- | --- |
| `index.json` | fixture names |
| `<name>.json` | one JBL250 round, both listeners (format below) |
| `nulls.json` | null-template vectors (seed hex, first 8 / last 4 samples, sums, one full float64 vector) + a pinned Gumbel sample with the scipy fit |

Picks: `2dc2eb59_k0` (touch), `b9e4dd4b_k0` (30 cm), `b2a5f86d_k1` (60, reads 60.03 -> NOT_NEAR), `d1ee4fb0_k0` (100), `f3ff0ee8_k0` (200), `glitch_synth` = `180ca04b` k0 with 20 ms of zeros written into B's crop halfway between B's two arrivals.

Per listener:

- `segment_pcm16_b64`: int16 LE crop of the recording, `[min window lo − 0.1 s, max window hi + 0.25 s + 0.1 s)`. `segment_offset` is the crop start in the full recording. All frames in the fixture (`expected`, `frame`, `window_lo/hi`, `flat_runs`, `score_probes`) are relative to the crop, i.e. the crop is the "capture".
- `windows.self|partner`: `expected` (float frames), `emitter`, `template_f32_b64` (field bed template, float32 LE).
- `expect.self|partner`: dsp_ref `measure_arrival` output + `null_maxima` (64) + `score_probes` (`[frame, score]` at 24 spread frames and the argmax).
- `expect.flat_runs` (`[start, end)`), `glitch_self` (run hits `[self w0, self w1 + L)`), `glitch` (run hits the union of both windows + L), `half`.

Top level: `session_id_hex` (field session id, used as the null seed), `attempt` (= round k), `expect_flight_cm`, `expect_verdict` (`NEAR` / `NOT_NEAR` / `glitch`), `notes`.

## Deviations and choices

- Field wavs are float32 (web capture). They are quantized as an AudioRecord would hold them: `clip(round(x·32768))`.
- Expected frames use the web prototype's timing (own play ctx time for self, schedule for partner), so `self_os_delta` in the fixtures is ~90 ms (browser output latency). The Kotlin test raises `selfOsTolFrames` for them; the contract's 50 ms stays the default.
- `dsp_ref` vs `fieldanalysis` (golden, in each fixture's `notes`): every arrival frame identical (0 samples), bars within ±10% (different null family, no ppm bank, different nfft). Flights agree to 0.01 cm.
- Contract §10.3 asks for a null-vector hash over `%.12e`-formatted doubles; common Kotlin has no printf, and a text hash breaks on last-digit rounding within the 1e-9 tolerance. `nulls.json` carries the full float64 vector for one case plus first/last samples and sums for eight (session, emitter, attempt, i, sr) cases, including 44100 (odd n = 11025), 36000 and 96000.
- Pinned literals in `NullTemplateTest` are this dsp_ref's output for `("00"*16, 'A', 0, 0, 48000)`; the server's `test_null_codes` should pin the same eight numbers.
