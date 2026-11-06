# Coverage: what's checked, and where it fails

Summary of [`../server/README.md`](../server/README.md) and [05-spike-results.md](05-spike-results.md). Those files have the evidence. Server work is pinned to `main` at 9db1490.

Colors: green is proved in Lean on a hand-written model. Yellow is tested or partly covered. Red is a known hole. Grey is not covered.

Every review track ended on a fail, so green doesn't mean a reviewer signed it off. Diagram 3 shows why.

## 1. The path to NEAR

Live NEAR takes the top route, from two signed numbers. The circuits run only after it, and nothing requires them.

```mermaid
flowchart TB
    air["Air and room<br/>Was there really a beep?"]:::out
    app["App finds arrivals<br/>AppPasses, AppParity, parity script"]:::part
    half["Phone signs its half<br/>X1: any number that fits gets NEAR"]:::hole
    auth["Request auth, R1<br/>Not in Lean. Replay guard can be dodged"]:::hole
    machine["Session state machine, M1 to M13<br/>Order, blind half, attempts, timing"]:::good
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
    B["Lean, walk and replay, with no named mutation<br/>V2 V3 M4 M9 M13"]:::good
    C["Lean, thinner testing<br/>V5: no replay<br/>V6: no walk check of its own<br/>M5: sounds compared by name, bodies scanned only<br/>M12: no-auth load untested"]:::part
    D["No general Lean theorem<br/>V7 on a final record<br/>V8 display rounding<br/>M14<br/>X2"]:::part
    E["Not modeled<br/>R1 auth: spot cases<br/>D1: reading only<br/>A2 A3 A9: assumptions"]:::out
    F["X1, the hole, proved<br/>The statement doesn't pin keys or deltas<br/>Session result is one concrete run"]:::hole

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
        s2 -- "Replay: 83,169 steps, 0 mismatches<br/>Sampled. One known false pass" --> s3
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
| `spec.md` | Opus | fail | Fixed, not re-reviewed |
| `test_walk.py` | Opus | fail, never finished | Final walk passed, not re-reviewed |
| `Verdict.lean` | Opus | fail, `X1` overclaim | Wording narrowed, statement not strengthened |
| `Machine.lean` | Opus | fail, two doc claims | Fixed, 21 of 21 mutants broke, not re-reviewed |
| `Replay.lean` | Codex | fail, false pass | **Not fixed** |
| Whole work, critic | Codex | fail, real gaps | **Not fixed**, listed as known gaps |
| Circuit `Commit`, `Freivalds`, `Signed`, `Chain` | Opus | see [05-spike-results.md](05-spike-results.md) | Last `Chain` wording fixes not re-reviewed |
