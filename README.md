# enconomy

Prove two phones were physically near each other, using sound.

Each phone plays a short tune with a secret noise layer under it and records both plays. Four arrival times give a distance that clock offsets can't fake. Under 60 cm reads NEAR.

Each phone signs its result with a hardware-bound key. A zero-knowledge proof ties that result to the recording without revealing the recording.

## Layout

- `research/sound-bound/`: the proximity check. Prototype, field tests, ZK spikes.
- `research/*.md`: decisions and threat model.
- `research/proximity-echo/`, `research/fuzzy-commitment/`: earlier approaches, retired.
- `circuits/`: early co-presence circuit.

## Demo stack

One command runs the whole PoP demo: server (:8001), World ID sidecar (:8787), ENS bridge, Safe relayer and the `pop.enconomy.dev` tunnel. Output is prefixed `[server]`, `[sidecar]`, … and also kept in `.demo/logs/`.

```sh
./demo check          # preflight: tools, node_modules, key + Sepolia balance, bridge/names.json, ports, tunnel
./demo up             # all five; Ctrl-C stops everything
./demo up --web       # + POP_ALLOW_WEB=1, POP_CORS_ORIGINS for https://webapp.enconomy.dev
./demo up --no-tunnel --no-ens --no-safe --no-worldid   # skip pieces
./demo status         # what runs + bridge status
```

Server config stays in `server/.env`. If a piece dies, a banner names it, the rest keeps running, and `./demo up` exits nonzero at the end. `./demo help` has the details.
