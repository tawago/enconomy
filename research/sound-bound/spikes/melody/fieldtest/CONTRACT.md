# fieldtest contract (v1)

Two builders, PY and WEB, work in parallel from this file alone. If something is not pinned here, pick the simplest option and write it in your README section or module docstring. Do not wait on each other.

## 0. What this is

One session = two phones, three probes played back to back in one continuous recording per phone: **N30 -> N1s -> JB**. Same placement, same room, same minute. The output answers: which probe separates 30 cm from 100 cm best, with what security margin, in real rooms.

Hard rules (both builders):

- Write only inside `research/sound-bound/spikes/melody/fieldtest/`. Everything above it is read-only. Importing from it is fine.
- Do not commit.
- Python: `/Users/takahiro_ogawa/dev/enconomy/research/proximity-echo/.venv/bin/python3` (numpy, scipy, soundfile, flask, flask_socketio are present).
- The browser never does DSP. It plays float32 buffers the server gives it and records.
- Every threshold lives as a named constant at the top of its module, with a one-line reason.

Path helpers (from any file in `fieldtest/`):

```
HERE    = Path(__file__).resolve().parent          # fieldtest/
MELODY  = HERE.parent                              # spikes/melody/  (melody_probes.py)
SB_ROOT = HERE.parents[2]                          # research/sound-bound/  (probes.py, analysis.py)
CERTS   = HERE.parents[3] / "fuzzy-commitment"     # cert.pem, key.pem
```

## 1. File layout and ownership

```
fieldtest/
  CONTRACT.md            architect (this file; builders do not edit)
  fieldprobes.py         PY   probe generation, templates, schedule constants
  fieldanalysis.py       PY   analyze_session(dir) -> result dict, writes result.json
  synth_field.py         PY   two-phone simulation of a whole session -> session dir
  compare.py             PY   table over many sessions
  server.py              WEB  Flask+SocketIO, TLS, port 5004
  templates/index.html   WEB
  static/app.js          WEB
  static/recorder-worklet.js   WEB (copy of ../../../static/recorder-worklet.js is fine)
  static/socket.io.min.js      WEB (copy of ../../../static/socket.io.min.js)
  run.sh                 WEB  check | serve | synth
  README.md              WEB  how to run + field protocol; PY may append a "## Signal side" section
  .gitignore             WEB  contains `data/`
  data/sessions/<id>/    runtime, real runs (server writes)
  data/synth/<id>/       runtime, simulated runs (synth_field writes)
```

WEB imports `fieldprobes` and `fieldanalysis` lazily (inside functions) so the server boots and serves pages before PY lands. If the import fails: probe endpoint returns 503 `{"error": "..."}`, analysis writes `{"status":"failed","reasons":["server_missing_signal_code: ..."]}`.

## 2. Probes (PY, `fieldprobes.py`)

Constants:

```
VERSION      = "fieldtest-v1"
PROBES       = ("N30", "N1s", "JB")
ROLES        = ("A", "B")
TARGET_RMS   = 0.15          # equal digital RMS for every probe before gain
MAX_PEAK     = 0.95          # render() never exceeds this
BAND_HZ      = (2000.0, 18000.0)
FADE_S       = 0.005
JB_BED_REL_DB = -6.0         # bed RMS re jingle RMS
JB_NOTCH_HZ  = 15.0          # +-Hz around each public jingle partial (both roles' tunes)
```

Secret material: `sub = sha256(f"fieldtest-v1|{seed_hex}|{probe}|{role}|{part}")`, used as a PCG64 seed (as `melody_probes._rng`), or as a hex seed string for `probes.generate`.

| probe | length | design |
|---|---|---|
| N30 | 30 ms | `probes.generate(sub_hex, role, sr)` with `sub_hex = sha256("fieldtest-v1|{seed}|N30|{role}|tones").hexdigest()`, rescaled to TARGET_RMS |
| N1s | 1.000 s | random-phase multisine on a 1 Hz grid over BAND_HZ, as `melody_probes._multisine`, 5 ms raised-cosine fades, TARGET_RMS |
| JB | 1.000 s | public jingle + secret bed, see below |

**JB jingle**: M-bell timbre from `melody_probes` (TUNE[role], NOTE_HZ, `partials(f0, "M-bell")`, attack, decay, k^-0.9 slope) with **no phase wander** and fixed public phases from `_rng("00"*32, role, "JB", "jingle")`. Implement it in fieldprobes without mutating `melody_probes` module globals (the server is threaded; verify3's monkeypatch is not allowed). Same jingle for every session.
**JB bed**: 1 Hz-grid random-phase multisine over BAND_HZ from the secret stream (`part="bed"`), RMS = jingle RMS x 10^(JB_BED_REL_DB/20). Sum, fade, normalize to TARGET_RMS.

Public API (exact signatures):

```python
generate(seed_hex: str, probe: str, role: str, sr: int) -> np.ndarray   # float32, RMS = TARGET_RMS
render(seed_hex, probe, role, sr, gain_db=0.0) -> (np.ndarray float32, dict)
    # applies gain; if peak would exceed MAX_PEAK, reduce gain until it does not.
    # info = {"gain_db_requested", "gain_db_applied", "peak", "rms", "n", "sr"}
template(seed_hex, probe, role, sr) -> np.ndarray float64
    # what the receiver correlates with: N30/N1s = generate(); JB = the BED ONLY
    # (same scaling and fades it has inside the JB waveform)
null_template(seed_hex, probe, role, sr, i: int) -> np.ndarray float64
    # template() of a fresh same-family code: seed = sha256(f"fieldtest-null|{seed_hex}|{probe}|{role}|{i}").hexdigest()
    # for JB this is a different bed (the jingle is shared and public, and is not in any template)
rx_mask(probe: str, nfft: int, sr: int) -> np.ndarray   # rfft-grid mask, 1 inside BAND_HZ, 0 outside;
    # JB additionally 0 within +-JB_NOTCH_HZ of every jingle partial of BOTH roles
plays(schedule: dict, role: str) -> list[dict]   # [{"probe","k","offset_s"}] sorted by offset_s
duration_s(probe) -> float
```

Rate handling: every waveform is a function of physical time (fixed Hz grid), so 44.1 k and 48 k give the same sound. Valid sr is 36000..96000; anything else raises ValueError.

`python fieldprobes.py` prints per probe and sr in (44100, 48000): n, rms, peak, crest dB, A/B template cross-correlation margin dB.

## 3. Schedule (PY owns the constant, WEB copies it verbatim into session.json)

`fieldprobes.SCHEDULE`, all times in seconds relative to **t0 = the shared start instant** (`start_ctx_s` on each phone):

```python
SCHEDULE = {
    "lead_s": 0.5,             # capture starts at t0 - lead_s
    "record_total_s": 19.0,    # capture covers [t0 - 0.5, t0 + 18.5)
    "search_pre_s": 0.150,     # window around expected onset
    "search_post_s": 0.250,
    "order": ["N30", "N1s", "JB"],
    "probes": {
        "N30": {"start_s": 0.0,  "rounds": 4, "period_s": 1.0, "b_offset_s": 0.5},
        "N1s": {"start_s": 4.5,  "rounds": 2, "period_s": 3.4, "b_offset_s": 1.7},
        "JB":  {"start_s": 11.5, "rounds": 2, "period_s": 3.4, "b_offset_s": 1.7},
    },
}
```

A plays probe p round k at `start_s + k*period_s`; B at `start_s + k*period_s + b_offset_s`.
Resulting timeline: N30 A 0,1,2,3 / B 0.5,1.5,2.5,3.5. N1s A 4.5, 7.9 / B 6.2, 9.6. JB A 11.5, 14.9 / B 13.2, 16.6 (ends 17.6).
For the 1 s probes every sound is followed by 0.7 s of silence before the next one (reverb settles; >= 0.6 s required even after up to 0.1 s latency skew). Last correlation needs audio to 16.6 + 0.25 + 1.0 = 17.85 s, capture ends at 18.5 s.

Gains: server reads env `FIELD_GAIN_DB="N30:0,N1s:0,JB:0"` (dB, missing = 0) at startup and stores it in session.json. Default is equal RMS.

## 4. Expected arrivals (mirrors `analysis.py`)

For listener L's recording, emitter E, probe p, round k:

```
own    (E == L): expected_s = play.ctx_s (from meta_L.plays, the value actually passed to start())  - meta_L.capture_start_ctx_s
partner(E != L): expected_s = meta_L.start_ctx_s + offset_E(p, k) - meta_L.capture_start_ctx_s
```

`offset_E` from session.json schedule. Ideal value = lead_s + offset. Search window over onset sample n: `[expected - search_pre_s, expected + search_post_s)`, clipped to the recording; if clipping removes it entirely the arrival is missing (`window_outside_recording`).

## 5. Receiver (PY, `fieldanalysis.py`)

Constants: `SPEED_OF_SOUND_CM_S = 34300`, `N_NULL = 64`, `NULL_P = 1e-4`, `HALF_FRAC = 0.5`, `PPM_BANK = (0, 25, -25, 50, -50, 75, -75)`, `FLAT_RUN_MIN_S = 0.008`, `NEAR_CM = 45`, `FAR_CM = 80`, `MIN_USABLE = 2`, `SPREAD_MAX_CM = 40`, `IMPOSSIBLE_CM = -20`.

Per (probe p, listener L):

1. Segment = recording span covering every window of p in L plus the longest template plus 0.1 s margin.
2. Mask: `X = rfft(seg, nfft) * rx_mask(p, nfft, sr)`, same mask on every template. Zero-phase, so no delay enters.
3. Score for template c (masked) at onset n:
   `score[n] = |<x[n:n+L], c + jH{c}>| / (||x[n:n+L]|| * ||c||)` (masked x). Envelope `env[n]` = the numerator. Compute via one FFT correlation with the analytic template spectrum; norms via cumulative sum of x^2.
4. ppm bank: for cross arrivals (E != L) and p in (N1s, JB), templates resampled to `round(L*(1+e*1e-6))` samples for every e in PPM_BANK; keep the e whose window-max score is highest. Self arrivals and all N30 use e = 0 only.
5. Live null, per window: score each of `null_template(seed, p, E, sr, i)`, i = 0..N_NULL-1, in the SAME window of the SAME recording, with the same bank rule (max over bank entries when the bank is used). Take each null's window maximum. Fit `scipy.stats.gumbel_r` to the N_NULL maxima; `T = gumbel_r.isf(NULL_P, loc, scale)`. Fallback if the fit fails: T = max of the nulls. One correlation per null code per bank entry over the whole segment, then slice all windows from it (do not re-correlate per window).
6. Arrival: first local maximum of env in the window with `env >= HALF_FRAC * max(env in window)` AND `score >= T`. None found -> missing, reason `below_null_<E>_at_<L>` if the window max score < T, else `no_arrival_<E>_at_<L>`. No MAD floor.
7. Per arrival record: `t` (s, onset in L's recording), `expected`, `right_pct` (100 x score at t), `right_max_pct` (100 x window max score), `T` (percent), `null_median` (percent), `margin_db` (20 log10(right_pct / T)), `window` ([lo_s, hi_s]), `ppm`, `partner_pct` (100 x window max score of the OTHER role's real template; informational, not a gate).

Round k of probe p:

- `flight_cm = c/2 * ((t_BA - t_AA) - (t_BB - t_AB))`, t_XY = X's code in Y's recording. Expected physical value = true distance minus the self path (about 12 cm).
- Unusable if any of the four arrivals missing.
- Unusable (`timeline_gap_at_<L>`) if any flat run (|diff| <= 1e-9 for >= FLAT_RUN_MIN_S; reuse `analysis._flat_runs`) in recording L intersects `[min window lo, max window hi + template length]` over that round's two windows in L. The "+ template length" is deliberate: a slip inside a 1 s code's body moves its arrival.
- Unusable (`impossible_flight`) if flight_cm < IMPOSSIBLE_CM.

Probe decision: usable = rounds with flight and no reasons. `< MIN_USABLE` -> UNDECIDED; spread (max-min) > SPREAD_MAX_CM -> UNDECIDED; median < NEAR_CM -> NEAR; > FAR_CM -> FAR; else UNDECIDED. Each decision carries a human `rule` string.

Runtime budget: under 60 s for a whole session on the Mac. If over, reduce N_NULL to 48 and say so in `constants`.

`python fieldanalysis.py <session_dir>` prints a per-probe summary and exits 0/1. `analyze_session` never raises; it writes `result.json` itself.

## 6. Session directory and JSON schemas

```
data/sessions/<session_id>/     (synth: data/synth/<session_id>/)
  session.json
  meta_A.json  meta_B.json
  recording_A.wav  recording_B.wav     mono IEEE float32 WAV (format 3), sr = the phone's AudioContext rate
  result.json
```

`session_id` = uuid4 hex (synth: `synth-<room>-<dist>cm-<8 hex>`).

**session.json** (server writes at pair-complete; updates `start_server_ms` and `roles[*].sample_rate` at start):

```json
{
  "version": "fieldtest-v1",
  "session_id": "…",
  "created_at": "2026-09-24T12:00:00.000+00:00",
  "seed_hex": "64 hex chars",
  "labels": {"label_cm": 30, "room": "small", "pose": "table", "noise": "quiet", "note": ""},
  "schedule": { ...SCHEDULE verbatim..., "start_server_ms": 1790000000000.0 },
  "gain_db": {"N30": 0.0, "N1s": 0.0, "JB": 0.0},
  "roles": {
    "A": {"client_id": "…", "sample_rate": 48000, "user_agent": "…",
          "render": {"N30": {…render info…}, "N1s": {…}, "JB": {…}}},
    "B": { … }
  },
  "synthetic": null
}
```

`label_cm`: number, `0` = touch, `null` = unknown. `room` in {small, big, other}; `pose` in {table, hand}; `noise` in {quiet, music, talk}. `synthetic` is `null` for real runs, otherwise the synth parameters dict.

**meta_<role>.json** (client uploads):

```json
{
  "role": "A",
  "sample_rate": 48000,
  "capture_start_ctx_s": 12.345,
  "capture_frames": 912000,
  "start_ctx_s": 12.845,
  "plays": [{"probe": "N30", "k": 0, "ctx_s": 12.845, "clamped": false}, …],
  "clock": {"server_offset_ms": 0.0, "rtt_ms_min": 0.0, "samples": 10},
  "context": {"base_latency_s": null, "output_latency_s": null, "state": "running"},
  "track_settings": {"echoCancellation": false, "noiseSuppression": false, "autoGainControl": false,
                     "sampleRate": 48000, "channelCount": 1},
  "blocks": {"count": 0, "frames": 912000, "discontinuities": 0, "missing_frames": 0},
  "probes_loaded": {"N30": {"n": 1440, "sr": 48000}, "N1s": {…}, "JB": {…}},
  "user_agent": "…",
  "events": [{"t_ctx_s": 1.0, "kind": "visibility:hidden"}]
}
```

`plays` has one entry per own play, 8 total per role. `clamped` = the scheduled time had already passed and the client used `currentTime + 0.01`.

**result.json**:

```json
{
  "status": "ok" | "failed",
  "version": "fieldtest-v1",
  "session_id": "…",
  "labels": { …copied from session.json… },
  "reasons": [],
  "quality": {"A": {"sample_rate", "duration_s", "flat_runs": [{"start_s","end_s","ms"}],
                    "clipped_samples", "worklet_discontinuities", "worklet_missing_frames",
                    "track_settings", "flags": []}, "B": {…}},
  "probes": {
    "N30": {
      "rounds": [
        {"k": 0, "flight_cm": 18.2, "delta_ms": 1.06, "usable": true, "reasons": [],
         "arrivals": {
           "A_at_A": {"t", "expected", "right_pct", "right_max_pct", "T", "null_median",
                      "margin_db", "window": [lo_s, hi_s], "ppm", "partner_pct"},
           "B_at_A": {…}, "B_at_B": {…}, "A_at_B": {…}
         }}
      ],
      "summary": {"flight_median": 18.2, "spread": 0.4, "usable_rounds": 4, "total_rounds": 4,
                  "min_margin_db": 9.1, "null_T_median": 17.0, "right_pct_median": 24.0,
                  "null_median_median": 12.0},
      "decision": {"label": "NEAR" | "FAR" | "UNDECIDED", "rule": "…", "provisional": true}
    },
    "N1s": {…}, "JB": {…}
  },
  "constants": { …every constant used… },
  "runtime_s": 12.3
}
```

A missing arrival is `null` in `arrivals`, but its window/T/null fields still appear in a sibling `"misses": {"B_at_A": {…}}` dict so the UI can show "right 6.1 % vs T 7.4 %". Unknown numbers are `null`, never NaN. `min_margin_db` is over arrivals of usable rounds (null if none).

## 7. Server (WEB, `server.py`)

Port 5004, HOST 0.0.0.0, TLS from `CERTS/cert.pem`, `CERTS/key.pem`. Same structure as `../../../server.py` (one pair at a time, atomic JSON writes, RLock).

HTTP:

| route | does |
|---|---|
| `GET /` | index.html |
| `GET /api/time` | `{"server_ms"}` |
| `GET /api/probe/<session_id>/<role>/<probe>.f32?sr=<int>` | raw little-endian float32 body of `fieldprobes.render(seed, probe, role, sr, gain_db[probe])[0]`; headers `X-Sample-Rate`, `X-Samples`. Records render info into session.json roles[role].render[probe]. 400 bad args, 404 unknown session, 503 signal code missing |
| `POST /api/upload/<session_id>/<role>` | multipart `wav` + `meta` (JSON string); writes recording_<role>.wav, meta_<role>.json; when both present, starts analysis in `socketio.start_background_task` |
| `GET /api/result/<session_id>` | result.json or 404 |
| `GET /sessions` | HTML table, newest first: id, created, label_cm, room, pose, noise, then per probe: decision, flight_median, spread, usable/total, min_margin_db |
| `GET /preview/<probe>.wav?role=A` | 16-bit PCM WAV at 48 kHz of `render(PREVIEW_SEED, probe, role, 48000, gain)` with 0.3 s silence each side, for listening. `PREVIEW_SEED = "11"*32`. Index page links all three |

Socket events (server -> client in italics):

| event | payload |
|---|---|
| `join` | `{label_cm, room, pose, noise, note, prefer_role: "A"|"B"|"any", user_agent}` |
| *`joined`* | `{session_id, role, partner_present, labels, schedule, probes: ["N30","N1s","JB"]}` to each member; re-sent to both when the pair completes |
| `arm` | `{session_id, sample_rate}` sent only after the client has fetched all three probes at that rate |
| *`armed`* | `{armed: ["A"]}` |
| *`start`* | `{session_id, start_server_ms, schedule, server_ms}`; `start_server_ms = now + 2500` |
| *`analyzing`* | `{session_id}` when both uploads land |
| *`result`* | `{session_id, result}` |
| *`pair_reset`* | `{why}` |
| *`error_msg`* | `{message}` |
| `abort` | `{}` resets the pair |

Pairing: first joiner creates the session (seed = `secrets.token_bytes(32).hex()`) and its labels are the session's labels. `prefer_role` is honored if free, else the other role. The second joiner's labels are ignored; `joined.labels` shows both phones what is recorded. Pair resets after the result broadcast or on a pre-start disconnect.

Analysis thread: `fieldanalysis.analyze_session(dir)`; on exception write a failed result.json. Broadcast `result`.

## 8. Client (WEB, `index.html`, `app.js`, `recorder-worklet.js`)

Reuse `../../../static/app.js` capture approach unchanged in substance:

- AudioContext created inside the Join click (`latencyHint: "interactive"`, `sampleRate: 48000` requested), resumed again inside the Arm click.
- getUserMedia with `echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1`; show getSettings(), warn loudly if EC is true.
- Worklet recorder posting blocks with `currentFrame`; discontinuity count; mic never routed to output (gain 0 node).
- Clock sync: 10 fetches of /api/time, min-RTT offset.
- On `start`: sample performance.now() and ctx.currentTime together, map `start_server_ms` to `start_ctx_s`; schedule every own play from `fieldprobes.plays` logic (A: `start_s + k*period_s`, B: plus `b_offset_s`) as its own AudioBufferSourceNode `start(when)`; record the `when` actually used in `meta.plays`.
- Capture trim: `startFrame = round((start_ctx_s - lead_s) * rate)`, `frames = round(record_total_s * rate)`, filled from blocks, holes counted in `missing_frames`. Upload float32 WAV + meta.
- Wake lock (fallback silent loop).

UI (phone, no typing required):

1. **Label**: distance as big buttons `touch(0) · 30 · 100 · 200 · other` (other reveals a number input); `room` select small/big/other; `pose` select table/hand; `noise` select quiet/music/talk; role select any/A/B; optional note. Last choices remembered in localStorage (try/catch). Join button.
2. **Session**: role, session id, partner state, labels as recorded, clock offset/RTT.
3. **Arm**: fetch the three probes at `ctx.sampleRate`, show `n @ sr` for each; then getUserMedia; then emit `arm`. Hint: media volume up, phones flat, quiet.
4. **Running**: countdown to start, then which probe is live (N30 / N1s / JB) and seconds left of 19.
5. **Result**: one row per probe: decision, flight_median, spread, usable/total, min_margin_db, T median. Tap a probe to expand per-round rows (flight, four right_pct vs T, reasons). Quality flags. Button "Next run" reloads with the labels kept.
6. Links: /sessions, /preview/N30.wav, /preview/N1s.wav, /preview/JB.wav.

## 9. Simulation (PY, `synth_field.py`)

`synth_field.py --dist-cm 30 --room small --noise quiet [--ppm-a 20 --ppm-b -30] [--slip B:9.0] [--sr-a 48000 --sr-b 44100] [--seed hex] [--out data/synth]`
`synth_field.py --walk` runs dist in (0, 30, 100, 200) x room in (small, big), noise quiet, random ppm within +-50, one session each, then prints the compare table for those sessions.

Writes session.json, meta_A/B.json, recording_A/B.wav exactly as §6 (labels from args, `synthetic` = all params), then calls `fieldanalysis.analyze_session`.

Model (reuse bakeoff.py pieces by import or copy: `rir`, `color_fir`, `add_delayed`, `warp`, `mp.speaker`):

- Rooms: `small = {rt60: 0.5, tail: 1.2, early: (0.05, 0.12)}` (bakeoff "harsh", calibrated to real N30 scores), `big = {rt60: 1.0, tail: 1.2, early: (0.02, 0.06)}`.
- Self path 12 cm, cross path dist (touch = 2 cm). Direct amplitude 1/r re self.
- Per phone: out latency and in latency U(0.02, 0.08) s, clock-sync residual U(-5, +5) ms, sample-clock ppm.
- Arrival of E's play scheduled at offset s, in L's recording (seconds of L's timeline): `lead + s + out_E + in_L + resid_E - resid_L + dist/c`, all real-time terms scaled by `(1+ppm_L)` and the emitted code stretched by `(1+ppm_L)/(1+ppm_E)`. Check: four-arrival flight = dist - 12 cm up to the drift term.
- Noise: quiet = white at -40 dB re self-path direct RMS; music = sum of slowly changing tones 200-5 kHz at -20 dB; talk = speech-shaped noise (100-4 kHz) with 4 Hz syllabic gating at -20 dB.
- `--slip L:t`: insert 960 zeros (20 ms at 48 k; scale to sr) at t in L's recording, later audio shifts late, keep length.
- `meta.track_settings` all false, `blocks` clean, `plays[*].ctx_s` consistent with the formula.

Acceptance (PY must see these before handing back): quiet small room: 30 cm -> NEAR and 100/200 cm -> FAR for all three probes; right_pct above T on all arrivals; one `--slip` inside an N1s round marks exactly that round `timeline_gap_at_<L>`; runtime per session under 60 s.

## 10. compare.py (PY)

`compare.py [--dir data/sessions] [--csv] [--by probe,room,label_cm]`

Reads every `<dir>/*/session.json` + `result.json`. One row per group (default probe x room x label_cm; pose and noise shown when not uniform):

`probe | room | label_cm | n | NEAR/FAR/UND | correct | flight_median (median of sessions) | worst spread | usable rounds (sum/total) | right% median | T median | min margin dB (min over sessions) | gaps`

`correct` = decisions matching the label: label <= 30 expects NEAR, >= 100 expects FAR, others blank. Markdown to stdout by default, CSV with `--csv`. Sort by probe order, then room, then label.

## 11. run.sh (WEB)

```
./run.sh check   # py_compile every fieldtest .py, node --check static/*.js (not socket.io.min.js), bash -n run.sh
./run.sh serve   # check, then exec python server.py  (https://0.0.0.0:5004)
./run.sh synth   # python synth_field.py --walk   (writes data/synth/, prints the table)
```

Python path is fixed (§0). `serve` passes `FIELD_GAIN_DB` through from the environment.

## 12. Not in scope

Signing, touch detection, DRR gating, iPhone-specific fixes, a codebook beyond per-session random codes, protecting a role's probe URL from the other phone (trusted-client spike).

## v2 addendum (2026-09-26): probes N250 / N500 / JBQ / JBL, two arrival rules

Supersedes sections 0, 2, 3 and parts of 5 where they conflict. Wire format unchanged.

- `fieldprobes.PROBES = (N30, N250, N500, N1s, JB, JBQ, JBL)` (all generatable);
  `fieldprobes.SEQUENCE = [N250, N500, N1s, JBQ, JBL]` is the default session.
- N250 / N500: as N1s, length 0.25 / 0.5 s (grid 4 / 2 Hz). JBQ: JB with bed at +6 dB re
  jingle. JBL: low public tune (partials < 1.8 kHz) + bed at -6 dB; rx mask = band only.
  Secret streams keep `sha256("fieldtest-v1|seed|probe|role|part")`.
- `SCHEDULE = build_schedule(SEQUENCE)`: 2 rounds, A then B, 0.7 s after every sound,
  `b_offset = dur + 0.7`, `period = 2 b_offset`, per-probe `dur_s`, `record_total_s = 30.0`.
- ppm bank on cross arrivals of every probe except N30; drift correction except N250.
- Every session is picked under `first` (primary) and `ownwalk`; alt results under
  round[`ownwalk`] and probe `summary_ownwalk` / `decision_ownwalk`.
- Self-arrival code-gap flag (`code_gap`, `self_code_gap_at_<L>`).
- `joined.probes` = the schedule order. `FIELD_PORT` overrides 5004.
- v2.1 (2026-09-26): new probe JBL250 = 0.25 s two-note low public ding-dong (partials < 1.8 kHz)
  + 0.25 s bed (grid 4 Hz) at -6 dB; rx mask = band only; bank ppm recorded, not applied (as N250).
  `PROBES` gains JBL250; `SEQUENCE = [N250, N500, N1s, JBL, JBL250]` (JBQ dropped from the default,
  still generated/analysed); `record_total_s = 27.0`.
