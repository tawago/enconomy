# Coverage: what's checked, and where it fails

Summary of [`../server/README.md`](../server/README.md) and [05-spike-results.md](05-spike-results.md). Those files have the evidence. Server work is pinned to `main` at 9db1490.

Colors: green is proved in Lean on a hand-written model. Yellow is tested or partly covered. Red is a known hole. Grey is not covered.

The last re-reviews of the server `spec.md` and `Machine.lean` passed, and so did the last critic. The `Verdict.lean`, `test_walk.py`, `Commit` and `Chain` re-reviews failed, and their fixes were not reviewed again. The Lean files added on 2026-11-07 had one chunk review each, no track review. On 2026-11-09 Codex (gpt-6-astra) reviewed again; the M14, `X1_session`, checker and replay fixes passed its re-review with low items open, and the doc fixes were not re-reviewed (report: [`../server/reviews/2026-11-09-codex.md`](../server/reviews/2026-11-09-codex.md)). So green doesn't mean a reviewer signed it off. Diagram 3 shows why.

## 1. The path to NEAR

Live NEAR takes the top route, from two signed numbers. The circuits run only after it, and nothing requires them.

```mermaid
flowchart TB
    air["Air and room<br/>Was there really a beep?"]:::out
    app["App finds arrivals<br/>AppPasses, AppParity, parity script"]:::part
    half["Phone signs its half<br/>X1, X1_session: any number that fits gets NEAR"]:::hole
    auth["Request auth, R1<br/>Not in Lean. Replay guard can be dodged"]:::hole
    machine["Session state machine, M1 to M14<br/>Order, blind half, attempts, timing, no trace on error<br/>M14: an error leaves the doc unchanged, any status,<br/>or a 400 transcript reject finalizes one of two pinned docs"]:::good
    verdict["Verdict math, V1 to V5<br/>NEAR iff checks pass and flight is between -20 and 60"]:::good
    near(["NEAR"])
    phone["phone circuit, blocks A B C D E F H<br/>Silence and a 500 Hz tone both pass"]:::hole
    pair["pair circuit, block G<br/>Silent pair reads 0 cm"]:::good
    chain["phone_sound, presence_sound<br/>Join of the blocks. Test cases are all silent"]:::part

    air -. "nothing checks this" .-> app
    app --> half
    half --> auth
    auth --> machine
    machine --> verdict
    verdict --> near
    near -. "optional, after NEAR" .-> phone
    phone --> pair
    phone --> chain
    pair --> chain

    classDef good fill:#c8e6c9,stroke:#2e7d32,color:#000
    classDef part fill:#fff3c4,stroke:#b58900,color:#000
    classDef hole fill:#ffcdd2,stroke:#c62828,color:#000
    classDef out fill:#e0e0e0,stroke:#757575,color:#000
```

## 2. Server properties by strength

```mermaid
flowchart LR
    A["Lean, walk with a named mutation, and replay<br/>V1 V4 M1 M2 M3 M6 M7 M8 M10 M11<br/>V1's role guard is never hit in replay"]:::good
    B["Lean, walk and replay, with no named mutation<br/>V2 V3 M4 M9 M13 M14<br/>M14 pins the rejected-transcript doc (TxReject), 2026-11-09"]:::good
    C["Lean, thinner testing<br/>V5: no replay<br/>V6: no walk check of its own<br/>V7 on a final record: no replay, rows 3 and 4 match the reason only<br/>M5: sounds compared by name in replay<br/>M12: no-auth load untested<br/>X2: fail and bad transcript on an arbitrary doc, not shown reachable"]:::part
    D["No Lean theorem<br/>V8 display rounding<br/>R1 and D1 have none either, see E"]:::part
    E["Not modeled<br/>R1 auth: spot cases<br/>D1: reading only<br/>A2 A3 A9: assumptions"]:::out
    F["X1, the hole, proved<br/>as a session result from create, any allowed numbers,<br/>stored commits and transcripts pinned<br/>One fixed schedule. Powers, hsha, hb64 assumed"]:::hole

    A --> B --> C --> D --> E
    E ~~~ F

    classDef good fill:#c8e6c9,stroke:#2e7d32,color:#000
    classDef part fill:#fff3c4,stroke:#b58900,color:#000
    classDef hole fill:#ffcdd2,stroke:#c62828,color:#000
    classDef out fill:#e0e0e0,stroke:#757575,color:#000
```

## 3. Where the chain from proof to real code is weak

A theorem is only about the model. Each arrow is a step that has to hold before it says anything about what runs today.

```mermaid
flowchart TB
    subgraph S["Server"]
        direction TB
        s1["Lean theorems<br/>no sorry, standard axioms"]:::good
        s2["Machine.lean, hand-written"]:::good
        s3["Python at 9db1490"]:::part
        s4["Current main"]:::hole
        s1 --> s2
        s2 -- "Replay: 83,329 steps, 0 mismatches<br/>Sampled. Label false pass fixed. 67 of 67 tampers caught" --> s3
        s3 -- "Not rerun. sessions.py and main.py changed" --> s4
    end
    subgraph C["Circuits"]
        direction TB
        c1["Lean theorems<br/>no sorry, standard axioms"]:::good
        c2["Popfv model, hand-written"]:::good
        c3["Noir, unchanged on main"]:::part
        c4["Real prover and verifier"]:::part
        c1 --> c2
        c2 -- "Checked by reading only. Lampe can't extract" --> c3
        c3 -- "nargo ran the cases. bb prove didn't" --> c4
    end

    classDef good fill:#c8e6c9,stroke:#2e7d32,color:#000
    classDef part fill:#fff3c4,stroke:#b58900,color:#000
    classDef hole fill:#ffcdd2,stroke:#c62828,color:#000
```

## Last review per track

| Track | Reviewer | Last verdict | Status after |
|---|---|---|---|
| `spec.md` | Opus, last round not recorded | pass, on re-review | Nits fixed after |
| `Machine.lean` | Opus, last round not recorded | pass, on re-review | Its `spec.md` nits fixed. 34 of 34 mutants break |
| `Verdict.lean` | Opus, last round not recorded | fail, on re-review: `X1_on_layout` docstrings | Docstrings now say what each statement pins, `X1_on_layout_keys` pins recording values. Not re-reviewed |
| `test_walk.py` | Opus, last round not recorded | fail, on re-review: run records | Not re-reviewed as a track. Its 2026-11-09 fixes passed Codex. Full walk on the current file, 62 passed |
| `Replay.lean` | Codex | fail, false pass | Fixed in code, gaps 15 and 16 added. Chunk reviews passed, no track re-review. Its 2026-11-09 fixes (recording length, `?`) passed Codex |
| Whole work, critic | Codex, then not recorded | pass, on the second critic | Its open items are listed in the server README |
| Circuit `Commit`, `Chain` | Opus, last round not recorded | fail, on re-review: wording and unlogged mutants | Wording fixed, mutants logged in `zkp/logs/chain-mutants.txt`. Not re-reviewed. See [05-spike-results.md](05-spike-results.md) |
| Circuit `Freivalds`, `Signed` | Opus | pass | See [05-spike-results.md](05-spike-results.md) |
| M14 fix, 2026-11-09 | Codex astra, Opus checked | pass | `TxReject` pins the doc. Open: no status limit on the unchanged case, combine reason, `M14_any` |
| `X1_session` fix, 2026-11-09 | Codex astra, Opus checked | pass | `X1Reached` pins run and stored values. Open: symmetric layout instances |
| Checkers, 2026-11-09 | Codex astra, Opus checked | pass, round 2 | Open: allow-list dots, empty argument, `owner()` |
| Replay and walk fixes, 2026-11-09 | Codex astra, Opus checked | pass | Open: `REPLAY_ONLY` matching nothing exits 0 |
| Docs, 2026-11-09 | Codex astra, first pass only | not re-reviewed | Fixed after the first pass |
