# ADR 0003: TLA+ for two honest devices together

Date: 2026-11-16. Status: accepted.

## Context

The Lean model in [`protocol/`](../protocol/README.md) is one honest device against an attacker who picks every input. It proves what that device never does: the order of its messages, the fixed code, the blind gap, freshness, its half of agreement, and the reader's check (FP1 to FP6). Four questions are outside it.

1. **Two honest devices together.** "Never NEAR on one honest device and NOT_NEAR on the other" is argued on paper from four single-device lemmas (spec FP5). No check runs both devices at once.
2. **The link closing mid-exchange.** The spec allows one side to hold NEAR while the other is incomplete. Nothing checks that nothing worse can happen.
3. **Finishing.** With the link up and no fault, do both devices reach a final outcome without waiting for the 600 s end? The Lean model says what a device never does, not that a run ends.
4. **Timeouts.** The retry rules of spec F10: no timeout after the device's own `GAP_VALUE`, one `FAIL` per attempt, the answer to a partner's retry `FAIL`, the move to attempt 1. The spec describes one run where two honest devices lose a session (F10, "Two honest devices can lose a session this way"). Nothing checks that this is the only such run.

These are questions about two state machines running side by side over a link that can close. A model checker answers them by walking every interleaving. A proof assistant would need an invariant for each, written by hand.

## Decision

1. **A TLA+ model of two honest devices, checked with TLC, in [`tla/`](../tla/README.md).** It covers the four questions above: agreement between the two devices, the link closing, finishing (a liveness property under fairness), and the timeout and retry rules of F10. Finishing is checked only with the link up, no timeout, and local failures only before the device's own `GAP_HASH`. A timeout, a link close, or a local failure after the own `GAP_HASH` can each leave a run that only the 600 s end closes.
2. **Lean keeps FP1 to FP6.** The TLA+ model does not restate them. It has no attacker: both devices are honest.
3. **The TLA+ model has no crypto.** No hashes, seeds, signatures, `sid` or `peer`. Between two honest devices every one of those checks is assumed to pass, as the spec argues (FP5), so they are left out. Neither model proves it, and hole K9 (a `render` that is not bit-exact) breaks it. The one check that can fail between honest devices, B's clock bounds check on `TIME`, is a fault the model can switch on.
4. **Drift rule.** Both models name the `spec.md` version they follow, as a git commit and the sections read, at the top of their README and, for TLA+, in the module header. When `spec.md` changes in a part either model covers, both models change in the same pull request, or the README of the one left behind says which version it still follows.

## Consequences

- The paper argument of FP5 gets a check for two honest devices: TLC walks every order of messages, every point where the link can close, every timeout before a device's own `GAP_VALUE`.
- The spec's known stuck run gets a check: with the link up and no 600 s end, every stuck end state of the model has its shape. A link close leaves other stuck states, which only the 600 s end closes. That covers this model's link and atomic steps, not every spec behavior. If TLC finds another stuck state, it may be a spec problem or a model choice, to be read case by case.
- The TLA+ model's agreement result rests on the Lean model's single-device facts for anything about content. The TLA+ model shows that the rules about when to sign, answer and move on fit together. It does not show that a `GAP_VALUE` a device accepts is the one the partner sent. That is Lean (`fp5_device`) plus HASH.
- A second model can drift from the first. The drift rule above is the guard.
- TLC needs Java 11 or newer. `Safety`, the main safety check, passes with a 1 GB heap.

## Options not taken

- **A two-device theorem in Lean.** One model, one language. But it needs a hand-written invariant over the joint state, and every change to a rule means redoing the proof. Liveness in Lean needs a fairness model and a termination measure, which is much more work than TLC's fairness check.
- **Tamarin (QUESTIONS Q6).** Answers a different question: what a Dolev-Yao attacker on the wire can learn or forge. That is FP1 to FP4 with a stronger attacker. It is not about two honest devices, link close or timeouts. Q6 stays open on its own terms.
- **Nothing.** Keep FP5 on paper and the stuck run as prose. Cheapest, but the F10 retry rules have changed twice already, and a third change would have no check.
