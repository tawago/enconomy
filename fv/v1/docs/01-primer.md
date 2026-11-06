# FV primer: five steps, plain words

Running example: block D, the arrival rule in `self_side` (`oalib/src/lib.nr`). It has a loop, so it shows
every step, including induction.

## Step 1: Informal spec

What you'd tell a teammate:

> `a_self` is the **first** moment my own beep is loud enough in my recording.

Fuzzy on purpose: "loud enough" compared to what? "first" counting from where?

Step 2 shows why this matters. As written, "loud enough" doesn't mean a beep was heard.

## Step 2: Formal spec

Pin every word down, using the code's names.

- **Lags**: positions 0..192 (K = 193) inside the search window.
- **Score at lag j**: `match(j) = I(j)² + Q(j)²`; `loudness(j) = recording energy at j × template energy`.
- **Loud enough**: `BAR × match(j) ≥ loudness(j)`, BAR = 4474747. Silence satisfies this too: 0 ≥ 0. The spike
  proved it. See [05-spike-results.md](05-spike-results.md).
- **Claim**: if the circuit accepts, there is a lag `a` such that
  1. every lag before `a` is not loud enough,
  2. lag `a` is loud enough,
  3. `a = a_self − p_self + 96` (from the signed transcript).

Now it's a yes/no statement.

## Step 3: Model the code

Rewrite the function as math the proof tool can read, line by line, same names.

**Noir numbers wrap.** They live on a clock that rolls over at a huge prime p (~77 digits). `-1` is `p − 1`.
The code uses that: "x ≥ 0" is written `x.assert_max_bit_size::<96>()` ("fits in 96 bits"). A real negative
number wraps to something huge and fails. That only works if real values never get near p. That's a
proof obligation (step 4).

The arrival isn't stored as a number. It's a list of flags:

```
u = 1 1 1 1 1 0 0 0 0 …
              ^ arrival = where the 1s stop
```

Per lag the code checks one thing, picked by the flags:
- `u[j] = 1` (before arrival): must NOT be loud enough
- `u[j-1] = 1, u[j] = 0` (the arrival): must BE loud enough
- after: nothing

## Step 4: Invariants and induction

The loop checks one lag at a time; the claim is about all lags at once. Induction connects them.

An **invariant** is a sentence that stays true after every loop step:

> After checking 0..j, `u[0..j]` is some 1s then some 0s, and `usum` = number of 1s so far.

- **Base case**: j = 0, one flag, trivially true.
- **Step**: if true up to j and the check `!u[j] | u[j-1]` passes ("no 1 after a 0"), true up to j+1.

So `usum` really is the arrival position, and `assert(usum == usum_target)` ties it to the signed `a_self`.

Other invariants needed, e.g. `ey`: "after m steps, `ey` = sum of the first m FIR outputs squared."

**No-wraparound lemma**: every value fed into a 96-bit check is truly within ±2⁹⁶. Proven by bounding
inputs (samples 16-bit, taps known, template int8) and multiplying the bounds through. Most likely place for a
real bug.

## Step 5: Machine-checked proof

Type steps 2–4 into a proof tool (Lean 4). It checks every step: ✓ airtight, or ✗ with the exact fact it
can't justify. An ✗ means a missing assumption or a real hole in the code. Both are worth finding.

```
theorem arrival_correct :
  self_side accepts  →  a is the first loud-enough lag  ∧  a = a_self − p_self + 96
```

## Words

| Word | Meaning here |
|---|---|
| Soundness | "If the verifier accepts, the claim is true." The security property. |
| Completeness | "An honest phone gets a proof." Usability, not security. |
| Underconstrained | A check is missing, so a cheater has a witness that passes but shouldn't. The classic ZK bug. |
| Invariant | A sentence true after every loop step. |
| Induction | Base case + "each step keeps it true" = true at the end. Dominoes. |
| Trusted base | What we assume without proof (hashes, signatures, compiler, prover). |
