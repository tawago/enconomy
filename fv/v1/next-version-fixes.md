# Fixes for the next circuit version

Memo, 2026-11-06. Nothing here is implemented or tested. The current FV work stays on today's circuit, frozen at `phone.json` sha256 `5499f99e…` and `pair.json` `7b740882…`. Evidence for each gap: `circuit-cases/RESULTS.md` and `fv/v1/docs/05-spike-results.md`.

Any circuit change needs a new verifier key, so do these together.

## Circuit and app rule

### 1. Measure `match` on the filtered audio

- **Closes:** the tone (gap 2).
- **Why:** today `loudness` goes through the FIR filter and `match` uses raw samples. A 500 Hz tone gets a gain of 0.14 on one side and 1 on the other, while the bar assumes about 190. That inflates its score about 1,400 times.
- **Change:** correlate the code with the FIR output. The gain then cancels at every frequency.
- **Bar:** `BAR` goes from 4474747 to about 123 (1 / 0.09²). Work out the exact value and the `y` bit widths.
- **Must match:** the rule changes in the circuit, `Popt2Rule.kt` and `server/pop/popt2.py` together. The stock app runs the same rule before the verdict, so a circuit-only fix leaves the live path open.
- **Check first:** honest scores on real walks, since the filter isn't perfectly flat across the band.

### 2. Require loudness above zero

- **Closes:** silence (gap 1), and the click (gap 3) on nearly all codes. One of 80 surveyed codes fell outside the click bound.
- **Change:** require `E × cn2 > 0` on the self side at the arrival lag, and on the partner side.
- **Doesn't close:** the tone. It has real energy.
- **Consider:** a higher floor, since the ratio test is scale-free and very quiet noise is judged like loud sound. Today's proofs don't cover this.

### 3. Include `c_q` in the template energy (optional)

- **Today:** `cn2` sums only `c_i`, while `match` uses both I and Q.
- **Why it matters:** an all-128 `c_i` gives zero energy and passes anything. It isn't reachable today because the server pins the code, but it reopens if the server goes away (gap 5).

## Decisions

### 4. Should something require proofs?

This decides how much the rest matters. Live NEAR comes from two signed numbers (`verdict.py:165`), and proofs are optional and come after it. Until something requires them, fixes 1 and 2 protect only the proof path. The app-side change in fix 1 still reaches live.

### 5. Bind devices, if a Noir guard ever ships

`NoirPresenceVerifier` returns `(0, 0)` (gap 10). Expose device hashes or key limbs as `pair` public inputs and bind them in the guard. Not live today. Put it in this version if a Noir guard is planned, because it needs a new key too.

### 6. Partner check: "loud enough" or "first"?

`partner_side` accepts any qualifying lag in the window (gap 6). Keep it or change it, and write down why.

## New concerns from the proofs

Found while proving blocks A, B and the chain. None is decided. Check each before changing anything.

### 7. Window past the end of the capture

The tree always has 256 leaves, padded with 32768, and the transcript has no capture length. So a window past the real capture reads silence padding and passes `partner_side`. Lean: `Commit.past_capture_witness`. Needs a dishonest signer. Not run in `nargo`, and not shown reachable through a whole statement.

### 8. Fields the circuit never reads

Partner Y (bytes 137-168), `commit_hash`, and the play and capture times reach the proof only through `sha256(t)`. The server compares whole keys (`verdict.py:159`), but `pair` sees X coordinates only. Lean: `Signed.junk_accepted`, `Signed.digest_only_free`. The holder commit is hashed and never opened: `Signed.holder_commit_free`.

### 9. Partner key is unchecked

No credential, signature or curve check on it. Only "X differs from own X" is enforced. Lean: `Signed.bad_keys_pass_byteChecks`, partner X = 1, Y = 0. The own key has no curve check of its own, and nothing checks low-S.

### 10. Whatever verifies must pin the public inputs

`issuer` and `code_commit` are whatever the public inputs say, and `valid_at` is only an upper bound against expiry. `pair` ties nothing across phones and doesn't link its commitments to a `phone` proof. Unpinned `code_commit` plus all-128 `c_i` passes on any audio: `WitnessChain.all128_self`. This sharpens fix 3.

## Server concerns

From the server FV work, `fv/v1/server/spec.md` section 6, with repros. All at `9db1490`, low severity, no wrong verdict, not fixed. Later commits changed `sessions.py` and `main.py`, and nothing was rerun, so check each one still applies.

- **R1-gap.** Key the replay cache on something canonical, not the signature's base64 string, and consider requiring low-s (`auth.py:45-46`, `crypto.py:32`).
- **R1-edge.** The 120 s forget window ends just as a ts 60 s ahead is still in range (`auth.py:36, 44`).
- **E500s.** Five inputs give 500 where a refusal is meant: `X-Pop-Ts` digits (`auth.py:36`), `reason` as a list (`sessions.py:465`), non-ASCII join token (`sessions.py:181`), deep create body (`main.py:155-158`), deep `meta` (`sessions.py:441-444`). The last one lets a member stall a session for up to about 600 s.
- **One worker.** Nothing enforces it for a `uvicorn --factory` start, and the session model and the replay cache need it.
- **`verify_record`.** Its docstring says "every check". It can't check timing, order, armed rate or `code_commit`, and doesn't compare the stored verdict. `cal_us` is under no signature.
- **`decide`.** NaN gives NEAR. No caller passes a float today.
- **`FINAL_REASONS`.** Dead code.
- **`combine`.** Rate 0 raises. Only a direct call reaches it.

None of this touches the main limit. The server follows its rules on signed numbers, and a phone can still sign a false half (CN1, X1).

## After the change

- Redo `Bar.lean`, `Arrival.lean` and `PartnerGlue.lean`. The silence and tone witnesses should stop working, and those theorems should flip.
- Add a new Lean theorem: for every recording, the score has a fixed ceiling (Cauchy–Schwarz). It holds only once both sides use the same signal, about 1 to 1.4 here.
- Rerun `circuit-cases/cases.py`. Silence, click, tone and fake near should all be rejected, and the control should still solve.
- Rerun on real walks to confirm honest phones still pass.
- New pins everywhere: vk, `phone.json`, the server and the app, in the same release.

## Not fixed by any of this

- A device can still report a false half on the plaintext path (CN1).
- Sound can't show who held the phone, or rule out a helper standing there (CN4, CN5).
