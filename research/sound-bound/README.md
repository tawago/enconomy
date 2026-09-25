# sound-bound

Two phones sit on a table. Each one plays its own short wideband code on a shared
schedule and records the whole exchange. The server hands out the seed and the start
time, collects both recordings, and works out three numbers: how far apart the two
phones must be for the round-trip timing to come out the way it did, how much of the
sound arrived direct rather than off the walls, and how cleanly each code separates
from the other. Target of the prototype: tell "these phones are touching" apart from
"these phones are a metre apart". Nothing more.

The reason to build it this way is that neither phone can be trusted to know its own
clock. Both codes go out on the same schedule, so the clock offset cancels in the
two-way difference and only the flight time survives. Every verdict is labelled
PROVISIONAL, because the thresholds here are first guesses, not measurements — the
five experiments below are what turn them into measurements.

## The five experiments

1. **Codes do not cross-fire.** Each role's code must beat the other's matched filter
   by `crossfire_db >= 20`, or the whole two-way argument collapses.
2. **The walk.** 10 cm, 30 cm, 100 cm, 10 sessions each. There has to be a visible gap
   between 30 and 100 in both `flight_cm` and DRR, or there is no line to draw.
3. **Holes are caught.** Inject 20 ms of recording dropout; rounds overlapping it must
   be discarded as `timeline_gap`, and the retry rate has to stay liveable.
4. **Relay margin.** Play the chirp through a video call. It should read as far away —
   that gap is the whole security claim.
5. **Sign and verify.** Later. Bind the measurement to keys.

## Running it

    ./run.sh check      # py_compile + node --check + bash -n
    ./run.sh serve      # the checks, then HTTPS on 0.0.0.0:5003

Open `https://<your-laptop-ip>:5003/` on both phones (accept the self-signed cert),
type the true separation in cm, press **Join** on both, then **Arm** on both. Put the
phones down, stay quiet for six seconds, and the result appears on both screens.
`/sessions` lists every past run for the walk.

Python comes from the proximity-echo venv; TLS from `../fuzzy-commitment/*.pem`.

## Layout

    server.py                    Flask + Socket.IO, sessions, uploads, analysis hand-off
    probes.py                    deterministic per-role probe waveforms
    analysis.py                  matched filter, arrivals, flight time, DRR, decision
    synth_check.py               signal sanity script (prints a table)
    run.sh                       check / serve
    templates/index.html         the one page
    static/app.js                join, arm, schedule, capture, upload, render
    static/recorder-worklet.js   float32 blocks + currentFrame continuity
    data/sessions/<id>/          session.json, recording_*.wav, meta_*.json, result.json

There are no tests. `synth_check.py` is a signal sanity script, not a suite: it
synthesizes known geometry and prints what the analysis recovers, so a human can see
whether the numbers move in the right direction.

## Endpoints and events

HTTP: `GET /`, `GET /sessions`, `GET /api/time`, `GET /api/result/<session_id>`,
`POST /api/upload/<session_id>/<role>` (multipart `wav` + `meta`).

Socket: client sends `join`, `arm`, `ping`, `abort`; server sends `hello`, `pong`,
`joined`, `armed`, `start`, `result`, `pair_reset`, `error_msg`.
