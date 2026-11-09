# Circuit cases: crafted inputs through the real compiled circuits

Run 2026-11-06 with `nargo execute`. Raw output: `../logs/circuit-cases.txt` (removed from the repo, in git at 5863e9c).

```bash
server/.venv/bin/python fv/v1/zkp/circuit-cases/cases.py        # all cases, about 75 s
server/.venv/bin/python fv/v1/zkp/circuit-cases/cases.py e      # one case
```

Circuits: `phone.json` is the artifact the server pins (sha256 `5499f99e…`, `server/pop/zk.py:49`). `pair.json` is `7b740882…`. Each `nargo execute` checks every constraint, including signature, Merkle tree and spot check. It makes no proof.

## Results

| Case | Input | Result |
|---|---|---|
| a. Control | Noise plus real codes, both phones, then `pair` | Solves. Flight 39.7 cm |
| a. Tamper | One sample +1 / one signature byte / nonce | All rejected: Merkle, signature, transcript |
| a. Far | Same phones, B's half moved by 2000 frames | `pair` rejects, 754 cm |
| b. Silence | All-zero recording, A and B | Both solve |
| c. Click | Silence plus one +1 sample, aimed at lag 50 | Solves, arrival lands on lag 50 |
| d. Tone | 10000-amplitude 500 Hz tone written to the file before any code exists, 6 fresh sessions, A side | 6/6 solve |
| e1. Both silent | Two silent phones with chosen halves, through `pair` | Solves, flight 0 cm |
| e2. One silent | B records real codes, A is silent and picks its half to fit B, through `pair` | Solves, flight 33.9 cm |

The control shows the harness can fail. So the passes mean something.

## What this shows

The real circuits accept recordings with no beep in them, and `pair` then reports NEAR. Nothing in the two recordings says where the phones were. The half is a free choice on the proof path, confirmed in the real circuit.

## What this doesn't show

- **The inputs are signed with throwaway keys, including the issuer.** A real run needs a credential the issuer signed, and a device key willing to sign a silent recording. The issuer is a public input, and a real verifier would reject the throwaway one.
- **e2 gives A knowledge of B's half.** A real cheater must guess it to about 5 ms or learn it with a mic near B. B's half is hidden until both transcripts are in.
- **e1 needs two cheaters.** Two who cooperate don't need this gap: they can share codes and synthesize perfect recordings.
- **d is a clean tone in a file.** It says nothing about a room. See `../logs/tone-room-2.txt` (removed from the repo, in git at 5863e9c) and `../logs/tone-distortion-sim.txt` (removed from the repo, in git at 5863e9c).
- **No proof was generated or verified.** `nargo execute` found a valid witness; `bb prove` wasn't run.
- **Live NEAR doesn't use these circuits.** It comes from two signed numbers (`verdict.py:165`). The stock app also refuses flat runs of 8 ms, so it wouldn't sign silence.

## Side note

In the control, the rule's first passing lag is 8 frames before where the code actually starts (lag 88, not 96). The bar is crossed early, on the way up to the peak. That moved the half by 8 frames each way here. It's on synthetic audio, and it hasn't been studied.
