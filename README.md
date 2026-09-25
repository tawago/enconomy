# enconomy

Prove two phones were physically near each other, using sound.

Each phone plays a short tune with a secret noise layer under it and records both plays. Four arrival times give a distance that clock offsets can't fake. Under 60 cm reads NEAR.

Each phone signs its result with a hardware-bound key. A zero-knowledge proof ties that result to the recording without revealing the recording.

## Layout

- `research/sound-bound/`: the proximity check. Prototype, field tests, ZK spikes.
- `research/*.md`: decisions and threat model.
- `research/proximity-echo/`, `research/fuzzy-commitment/`: earlier approaches, retired.
- `circuits/`: early co-presence circuit.
