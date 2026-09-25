# Proximity-Echo simulation

This simulation renders recordings for two virtual devices in a 3D room, then sends
them through the paper pipeline: alignment, feature extraction, compensation, scoring,
and verdict generation. It changes the microphone capture only. The protocol and scorer
are the same code used for a live trial.

```
Scene (3D room, 2 devices) -> pyroomacoustics RIRs -> render 2 WAVs -> pipeline -> verdict
```

The model includes room reflections, air and wall absorption, device orientation,
speaker response, clock offset and drift, output latency, microphone gain, noise, AGC,
and clipping. `pyroomacoustics` computes room impulse responses with the image-source
method.

## Files

| File | Purpose |
|---|---|
| `scene.py` | Device, room, and trial models; room impulse responses; recording renderer; pipeline integration. |
| `scenarios.py` | Pre-built scenes including same-room, different-room, remote-attacker, and colocated-attacker cases. |
| `sweep.py` | Distance and seed sweep with separation analysis. |
| `demo.py` | Runs the labelled scenario matrix. `--save` writes WAV files. |
| `viewer.py` | Interactive 3D scene viewer and simulator. |

## Commands

From `research/proximity-echo`:

```bash
source .venv/bin/activate
pip install -r requirements.txt
./run.sh check
./run.sh serve
```

`./run.sh check` parses the first-party Python and browser JavaScript files, excluding
vendored `socket.io.min.js`, and runs `bash -n` on the launcher. It catches syntax errors
only. It does not establish that the acoustic algorithm is correct.

`./run.sh serve`, and `./run.sh` with no argument, run those checks before starting the
HTTPS server.

To work with the simulator:

```bash
cd simulation
python sweep.py --beeps 20 --seeds 8
python demo.py --save ../data/sim_audio
python viewer.py
```

`viewer.py` shows the room and the devices. Its controls change device distance and
orientation, signal-to-noise ratio, wall absorption, and the room relationship. Run the
scene to render and score the recordings. Increase `BEEPS` in `viewer.py` when a longer
recording is useful.

`demo.py --save` writes `<label>_initiator.wav` and `<label>_observer.wav`. You can inspect
them with the existing analysis tools.

## Scope and limits

The shared-room model uses image-source room impulse responses. Inter-room cases use a
parameterized through-wall path with attenuation, low-pass filtering, and an independent
diffuse tail because one `pyroomacoustics` ShoeBox cannot model transmission through a
wall.

Treat absolute scores as model output, not a hardware calibration. The paper's 0.78
threshold depends on the hardware setup. The simulator is useful for comparing geometry,
orientation, and attack conditions, then planning physical trials.

At distances below about 10 cm, image-source direct paths can produce unrealistic peaks.
The validated scenarios use 30 cm and 100 cm, so treat shorter-distance results with care.
