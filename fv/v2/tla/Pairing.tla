------------------------------- MODULE Pairing -------------------------------
(***************************************************************************)
(* Two honest devices, A and B, run one v2 pairing session over the       *)
(* direct link.                                                            *)
(*                                                                         *)
(* Follows fv/v2/spec.md at commit 45e4da9, plus the two F10 sentences    *)
(* added with this model (nothing signed after the own FAIL; no local-     *)
(* failure FAIL after the own GAP_HASH): section 2.1 (resend, drop         *)
(* rules), the 2.3 table ("sends when" and receiver rules), F10 (failures, *)
(* retry, timeouts, the 600 s end) and the outcome of section 4. The Lean  *)
(* model in ../protocol follows the same version. See ADR 0003.            *)
(*                                                                         *)
(* Seven mutants, one value of Mutant each (MutantNames below), M1 to M7   *)
(* in tla/README.md.                                                       *)
(*                                                                         *)
(* No crypto. Between two honest devices every signature, sid, role, peer  *)
(* and body check is assumed to pass (spec FP5 argues it; neither model    *)
(* proves it), so they are left out. The one check that can fail     *)
(* is B's clock bounds check on TIME, which is a fault switch here.        *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Vals,             \* the values a good measurement can put in a transcript
    AllowTimeout,     \* a device may sign a timeout FAIL before its own GAP_VALUE
    AllowClose,       \* the link may close at any time
    AllowSessionEnd,  \* a device may reach the 600 s end at any time
    AllowLocalFail,   \* a measurement may fail on the device (a retry reason)
    AllowLateLocalFail, \* a local failure may also come after the own GAP_HASH (spec F10 forbids it)
    AllowTimeFail,    \* B's clock bounds check on A's TIME may fail (a retry reason)
    Mutant            \* "none", or one of MutantNames: a deliberately broken rule

MutantNames == {"answerAfterGapValue", "timeoutAfterGapValue",
                "nextAttemptWithoutFails", "nextAttemptWithoutPartnerFail",
                "bCombinesOwnFirst", "signAfterFail",
                "gapValueWithoutPartnerGapHash"}

ASSUME Vals # {} /\ Vals \subseteq Nat
ASSUME Mutant \in {"none"} \cup MutantNames

Devices  == {"A", "B"}
Partner(d) == IF d = "A" THEN "B" ELSE "A"
Attempts == {0, 1}
Tags == {"SEED_HASH", "SALT", "TIME", "REC_HASH", "SEED_VALUE",
         "GAP_HASH", "GAP_VALUE", "FAIL"}

(* The verdict of a pair of transcripts, A's first. A stand-in for the     *)
(* v1 math, where NEAR needs the flight in a window that is not symmetric  *)
(* around 0. Over Vals = {0, 1, 2}: near for (0,0) (0,1) (1,1) (1,2), too  *)
(* far for (0,2), impossible for (1,0) (2,0) (2,1), self timing mismatch   *)
(* for (2,2). Swapping the order turns (0,1) and (1,2) into impossible.    *)
Combine(a, b) ==
    IF a > b THEN "impossible"
    ELSE IF b - a > 1 THEN "tooFar"
    ELSE IF a = b /\ a >= 2 THEN "selfTiming"
    ELSE "near"

(* A signed message. v is the transcript value for GAP_VALUE, the retry    *)
(* bit (always 1, no final failure happens between honest devices) for     *)
(* FAIL, and 0 otherwise.                                                  *)
Msg(d, t, j, v) == [from |-> d, tag |-> t, k |-> j, v |-> v]

(* A measurement result: a value in Vals, or a local failure. *)
NotMeasured == [result |-> "none", v |-> 0]
MeasureResults ==
    {[result |-> "value", v |-> x] : x \in Vals}
    \cup (IF AllowLocalFail THEN {[result |-> "fail", v |-> 0]} ELSE {})

VARIABLES
    linkUp,     \* the link is open; a signed message reaches the partner only while it is
    signed,     \* every message either device signed (both devices, one set)
    accepted,   \* accepted[d]: the partner messages d accepted
    attempt,    \* attempt[d]: d's current attempt, 0 or 1
    confirmed,  \* confirmed[d]: d's person tapped confirm
    captured,   \* captured[d][j]: d's own capture for attempt j is over
    measured,   \* measured[d][j]: the result of d's measurement for attempt j
    over        \* over[d]: d reached the 600 s end

vars == <<linkUp, signed, accepted, attempt, confirmed, captured, measured, over>>

TypeOK ==
    /\ linkUp \in BOOLEAN
    /\ signed \subseteq [from : Devices, tag : Tags, k : Attempts, v : Vals \cup {0, 1}]
    /\ \A d \in Devices : accepted[d] \subseteq signed
    /\ attempt \in [Devices -> Attempts]
    /\ confirmed \in [Devices -> BOOLEAN]
    /\ captured \in [Devices -> [Attempts -> BOOLEAN]]
    /\ measured \in [Devices -> [Attempts -> {NotMeasured} \cup MeasureResults]]
    /\ over \in [Devices -> BOOLEAN]

Init ==
    /\ linkUp = TRUE
    /\ signed = {}
    /\ accepted = [d \in Devices |-> {}]
    /\ attempt = [d \in Devices |-> 0]
    /\ confirmed = [d \in Devices |-> FALSE]
    /\ captured = [d \in Devices |-> [j \in Attempts |-> FALSE]]
    /\ measured = [d \in Devices |-> [j \in Attempts |-> NotMeasured]]
    /\ over = [d \in Devices |-> FALSE]

-----------------------------------------------------------------------------
(* Reading a device's log *)

HasSigned(d, j, t)   == \E m \in signed : m.from = d /\ m.k = j /\ m.tag = t
HasAccepted(d, j, t) == \E m \in accepted[d] : m.k = j /\ m.tag = t
Log(d) == {m \in signed : m.from = d} \cup accepted[d]

HoldsPair(d, j) == HasSigned(d, j, "GAP_VALUE") /\ HasAccepted(d, j, "GAP_VALUE")

GapValueIn(d, r, j) ==
    (CHOOSE m \in Log(d) : m.from = r /\ m.k = j /\ m.tag = "GAP_VALUE").v

(* The verdict d computes from the pair it holds for attempt j. *)
Verdict(d, j) ==
    IF Mutant = "bCombinesOwnFirst" /\ d = "B"
    THEN Combine(GapValueIn(d, "B", j), GapValueIn(d, "A", j))
    ELSE Combine(GapValueIn(d, "A", j), GapValueIn(d, "B", j))

(* Holds both GAP_VALUEs for its attempt, and the verdict asks for a retry. *)
PairAsksRetry(d) ==
    LET j == attempt[d] IN
    HoldsPair(d, j) /\ Verdict(d, j) \in {"impossible", "selfTiming"}

(* The last attempt in d's log, as the spec's Outcome reads it. Right   *)
(* after the move to attempt 1 and before any message for it, this is  *)
(* still 0.                                                             *)
LogAttempt(d) == IF \E m \in Log(d) : m.k = 1 THEN 1 ELSE 0

(* Spec section 4, for the last attempt in the device's log. *)
Outcome(d) ==
    LET j == LogAttempt(d) IN
    IF \E m \in Log(d) : m.k = j /\ m.tag = "FAIL" THEN "notNear"
    ELSE IF HoldsPair(d, j)
         THEN IF Verdict(d, j) = "near" THEN "near" ELSE "notNear"
         ELSE "incomplete"

-----------------------------------------------------------------------------
(* Protocol steps of one device *)

Running(d) == confirmed[d] /\ ~over[d]

(* Free slot, and no FAIL signed for this attempt: after its FAIL a device *)
(* signs nothing more for the attempt. Agreement needs this rule (mutant   *)
(* signAfterFail drops it).                                                *)
MaySign(d, t) ==
    /\ Running(d)
    /\ ~HasSigned(d, attempt[d], t)
    /\ (~HasSigned(d, attempt[d], "FAIL")
        \/ (Mutant = "signAfterFail" /\ t # "FAIL"))

Sign(d, t, v) == signed' = signed \cup {Msg(d, t, attempt[d], v)}

Confirm(d) ==
    /\ ~confirmed[d]
    /\ ~over[d]
    /\ confirmed' = [confirmed EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<linkUp, signed, accepted, attempt, captured, measured, over>>

(* For attempt 1 the guard "both FAILs for 0 held" is NextAttempt's. *)
SignSeedHash(d) ==
    /\ MaySign(d, "SEED_HASH")
    /\ Sign(d, "SEED_HASH", 0)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

SignSalt(d) ==
    /\ MaySign(d, "SALT")
    /\ HasAccepted(d, attempt[d], "SEED_HASH")
    /\ Sign(d, "SALT", 0)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

SignTime ==
    /\ MaySign("A", "TIME")
    /\ HasAccepted("A", attempt["A"], "SALT")
    /\ Sign("A", "TIME", 0)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* t0 is known: A signed TIME, or B accepted it. *)
HasStartTime(d) ==
    IF d = "A" THEN HasSigned("A", attempt["A"], "TIME")
               ELSE HasAccepted("B", attempt["B"], "TIME")

(* The device's clock passes t0 + 2.0 s. It plays and captures only once it *)
(* holds the partner SALT (the code needs it).                              *)
CaptureOver(d) ==
    LET j == attempt[d] IN
    /\ Running(d)
    /\ ~captured[d][j]
    /\ ~HasSigned(d, j, "FAIL")
    /\ HasStartTime(d)
    /\ HasAccepted(d, j, "SALT")
    /\ captured' = [captured EXCEPT ![d][j] = TRUE]
    /\ UNCHANGED <<linkUp, signed, accepted, attempt, confirmed, measured, over>>

SignRecHash(d) ==
    LET j == attempt[d] IN
    /\ MaySign(d, "REC_HASH")
    /\ HasAccepted(d, j, "SALT")
    /\ captured[d][j]
    /\ Sign(d, "REC_HASH", 0)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

SignSeedValue(d) ==
    LET j == attempt[d] IN
    /\ MaySign(d, "SEED_VALUE")
    /\ HasAccepted(d, j, "REC_HASH")
    /\ HasSigned(d, j, "REC_HASH")
    /\ Sign(d, "SEED_VALUE", 0)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* F7, the local measurement. Its result is free. *)

Measure(d) ==
    LET j == attempt[d] IN
    /\ Running(d)
    /\ measured[d][j] = NotMeasured
    /\ ~HasSigned(d, j, "FAIL")
    /\ HasAccepted(d, j, "SEED_VALUE")
    /\ \E r \in MeasureResults : measured' = [measured EXCEPT ![d][j] = r]
    /\ UNCHANGED <<linkUp, signed, accepted, attempt, confirmed, captured, over>>

SignLocalFail(d) ==
    /\ MaySign(d, "FAIL")
    /\ measured[d][attempt[d]].result = "fail"
    /\ Sign(d, "FAIL", 1)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* Waits for the device's own SEED_VALUE, as the Lean model does. *)
SignGapHash(d) ==
    LET j == attempt[d] IN
    /\ MaySign(d, "GAP_HASH")
    /\ measured[d][j].result = "value"
    /\ HasSigned(d, j, "SEED_VALUE")
    /\ Sign(d, "GAP_HASH", 0)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* Also waits for the device's own GAP_HASH, which stands for "F7 gave a  *)
(* gap" (the value comes from the measurement), as the Lean model does.   *)
(* Mutant gapValueWithoutPartnerGapHash drops the partner GAP_HASH guard. *)
SignGapValue(d) ==
    LET j == attempt[d] IN
    /\ MaySign(d, "GAP_VALUE")
    /\ (HasAccepted(d, j, "GAP_HASH") \/ Mutant = "gapValueWithoutPartnerGapHash")
    /\ HasSigned(d, j, "GAP_HASH")
    /\ Sign(d, "GAP_VALUE", measured[d][j].v)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* Holds both GAP_VALUEs and the verdict is impossible or a self timing *)
(* mismatch: a retry FAIL after the own GAP_VALUE.                      *)
SignPairRetry(d) ==
    /\ MaySign(d, "FAIL")
    /\ PairAsksRetry(d)
    /\ Sign(d, "FAIL", 1)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* What a receiver expects now, beyond a free slot. Spec 2.3 states this *)
(* only for TIME. The SEED_VALUE and GAP_VALUE rows come from the Lean    *)
(* model: on this any-order link they turn an early message into a drop   *)
(* (it comes again) instead of a body check failure.                      *)
Expects(d, m) ==
    CASE m.tag = "SEED_VALUE" -> HasAccepted(d, m.k, "SEED_HASH")
      [] m.tag = "GAP_VALUE"  -> HasAccepted(d, m.k, "GAP_HASH")
      [] m.tag = "TIME"       -> d = "B" /\ HasAccepted(d, m.k, "SALT")
      [] OTHER                -> TRUE

(* A partner message on the link that d accepts now. The message is not *)
(* taken off the link: the sender resends it until it is answered, and  *)
(* a copy that is not expected yet is dropped and comes again. So any   *)
(* signed, not yet accepted message may arrive, in any order.           *)
CanReceive(d, m) ==
    /\ linkUp
    /\ Running(d)
    /\ m.from = Partner(d)
    /\ m.k = attempt[d]
    /\ ~HasAccepted(d, m.k, m.tag)
    /\ Expects(d, m)

(* The answer to a partner retry FAIL: only if d signed no FAIL for the   *)
(* attempt, and either has not sent its GAP_VALUE or the pair asks for a  *)
(* retry.                                                                 *)
AnswersFail(d) ==
    /\ ~HasSigned(d, attempt[d], "FAIL")
    /\ \/ ~HasSigned(d, attempt[d], "GAP_VALUE")
       \/ PairAsksRetry(d)
       \/ Mutant = "answerAfterGapValue"

Receive(d, m) ==
    /\ CanReceive(d, m)
    /\ accepted' = [accepted EXCEPT ![d] = @ \cup {m}]
    /\ IF m.tag = "FAIL" /\ AnswersFail(d)
       THEN Sign(d, "FAIL", 1)
       ELSE UNCHANGED signed
    /\ UNCHANGED <<linkUp, attempt, confirmed, captured, measured, over>>

ReceiveAny(d) == \E m \in signed : Receive(d, m)

(* F10: both retry FAILs for attempt 0 held, and either no own GAP_VALUE *)
(* for 0 or the pair asks for a retry. Every FAIL here is a retry FAIL.  *)
NextAttempt(d) ==
    /\ Running(d)
    /\ attempt[d] = 0
    /\ (Mutant = "nextAttemptWithoutFails" \/ HasSigned(d, 0, "FAIL"))
    /\ (Mutant \in {"nextAttemptWithoutFails", "nextAttemptWithoutPartnerFail"}
        \/ HasAccepted(d, 0, "FAIL"))
    /\ (~HasSigned(d, 0, "GAP_VALUE") \/ PairAsksRetry(d))
    /\ attempt' = [attempt EXCEPT ![d] = 1]
    /\ UNCHANGED <<linkUp, signed, accepted, confirmed, captured, measured, over>>

ProtocolStep(d) ==
    \/ Confirm(d)
    \/ SignSeedHash(d)
    \/ SignSalt(d)
    \/ (d = "A" /\ SignTime)
    \/ CaptureOver(d)
    \/ SignRecHash(d)
    \/ SignSeedValue(d)
    \/ Measure(d)
    \/ SignLocalFail(d)
    \/ SignGapHash(d)
    \/ SignGapValue(d)
    \/ SignPairRetry(d)
    \/ ReceiveAny(d)
    \/ NextAttempt(d)

-----------------------------------------------------------------------------
(* Faults. None of these is fair: they may happen, never must. *)

(* B's clock bounds check on A's TIME fails: B signs a retry FAIL. The   *)
(* TIME is not accepted, and stays on the link.                          *)
TimeFail ==
    LET j == attempt["B"] IN
    /\ AllowTimeFail
    /\ linkUp
    /\ MaySign("B", "FAIL")
    /\ ~HasSigned("B", j, "GAP_VALUE")
    /\ Msg("A", "TIME", j, 0) \in signed
    /\ ~HasAccepted("B", j, "TIME")
    /\ HasAccepted("B", j, "SALT")
    /\ Sign("B", "FAIL", 1)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* A local failure other than the measurement's own result, such as a    *)
(* failed capture: any time before the device's own GAP_HASH (spec F10).  *)
(* With AllowLateLocalFail, any time before the own GAP_VALUE, as the     *)
(* Lean model allows. The measurement's own failure is a result of Measure. *)
LocalFail(d) ==
    /\ AllowLocalFail
    /\ MaySign(d, "FAIL")
    /\ ~HasSigned(d, attempt[d], "GAP_VALUE")
    /\ (~HasSigned(d, attempt[d], "GAP_HASH") \/ AllowLateLocalFail)
    /\ Sign(d, "FAIL", 1)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

(* No progress: any time before the device's own GAP_VALUE. The spec's *)
(* clock rule (t0 + 20 s, or 60 s after the last new message) picks a  *)
(* subset of these points.                                             *)
Timeout(d) ==
    /\ AllowTimeout
    /\ MaySign(d, "FAIL")
    /\ (~HasSigned(d, attempt[d], "GAP_VALUE") \/ Mutant = "timeoutAfterGapValue")
    /\ Sign(d, "FAIL", 1)
    /\ UNCHANGED <<linkUp, accepted, attempt, confirmed, captured, measured, over>>

CloseLink ==
    /\ AllowClose
    /\ linkUp
    /\ linkUp' = FALSE
    /\ UNCHANGED <<signed, accepted, attempt, confirmed, captured, measured, over>>

SessionEnd(d) ==
    /\ AllowSessionEnd
    /\ ~over[d]
    /\ over' = [over EXCEPT ![d] = TRUE]
    /\ UNCHANGED <<linkUp, signed, accepted, attempt, confirmed, captured, measured>>

Fault ==
    \/ TimeFail
    \/ CloseLink
    \/ \E d \in Devices : LocalFail(d) \/ Timeout(d) \/ SessionEnd(d)

Next == (\E d \in Devices : ProtocolStep(d)) \/ Fault

Fairness ==
    /\ WF_vars(SignTime)
    /\ \A d \in Devices :
        /\ WF_vars(Confirm(d))
        /\ WF_vars(SignSeedHash(d))
        /\ WF_vars(SignSalt(d))
        /\ WF_vars(CaptureOver(d))
        /\ WF_vars(SignRecHash(d))
        /\ WF_vars(SignSeedValue(d))
        /\ WF_vars(Measure(d))
        /\ WF_vars(SignLocalFail(d))
        /\ WF_vars(SignGapHash(d))
        /\ WF_vars(SignGapValue(d))
        /\ WF_vars(SignPairRetry(d))
        /\ WF_vars(ReceiveAny(d))
        /\ WF_vars(NextAttempt(d))

Spec == Init /\ [][Next]_vars /\ Fairness

(* The same without fairness, for the safety checks. *)
SafetySpec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties *)

(* Never near on one device and not near on the other. *)
Agreement ==
    /\ ~(Outcome("A") = "near" /\ Outcome("B") = "notNear")
    /\ ~(Outcome("B") = "near" /\ Outcome("A") = "notNear")

NearStays == [][\A d \in Devices : Outcome(d) = "near" => Outcome(d)' = "near"]_vars

(* No protocol step of either device can happen. *)
Terminal == ~ENABLED (\E d \in Devices : ProtocolStep(d))

(* d signed a retry FAIL on attempt 0, or holds a pair that asks for one: *)
(* it is waiting to start attempt 1.                                      *)
WantsRetry(d) ==
    attempt[d] = 0 /\ (HasSigned(d, 0, "FAIL") \/ PairAsksRetry(d))

(* near, or not near with no next attempt to wait for. Final and          *)
(* WaitsForFail do not read the 600 s end: a device that signed a FAIL and *)
(* reached the end still counts as waiting. Every config that uses them    *)
(* has AllowSessionEnd = FALSE.                                            *)
Final(d) ==
    \/ Outcome(d) = "near"
    \/ Outcome(d) = "notNear" /\ ~WantsRetry(d)

(* d signed a retry FAIL for its attempt and holds none from the partner: *)
(* it waits for the partner's FAIL (spec F10).                             *)
WaitsForFail(d) ==
    HasSigned(d, attempt[d], "FAIL") /\ ~HasAccepted(d, attempt[d], "FAIL")

(* With no fault that needs a fallback, both devices stop with final,   *)
(* equal outcomes, and neither waits for a FAIL from the partner.       *)
Liveness ==
    <>[](/\ Terminal /\ Final("A") /\ Final("B") /\ Outcome("A") = Outcome("B")
         /\ ~WaitsForFail("A") /\ ~WaitsForFail("B"))

(* The end state of the run in spec F10, "Two honest devices can lose a  *)
(* session this way", on either attempt: x signed a retry FAIL after its  *)
(* GAP_HASH and before its GAP_VALUE; y sent its GAP_VALUE, holds no pair, *)
(* and so neither answers nor moves on. It is a state, not an order: y's  *)
(* GAP_VALUE may come before or after x's FAIL.                           *)
KnownStuckRun ==
    \E x \in Devices :
        LET y == Partner(x)
            j == attempt[x] IN
        /\ attempt[y] = j
        /\ HasSigned(x, j, "GAP_HASH")
        /\ HasSigned(x, j, "FAIL") /\ ~HasSigned(x, j, "GAP_VALUE")
        /\ HasSigned(y, j, "GAP_VALUE") /\ ~HasSigned(y, j, "FAIL")
        /\ ~HoldsPair(y, j)
        /\ Outcome(x) = "notNear" /\ Outcome(y) = "notNear"

(* Every state where the protocol cannot move and some device is not    *)
(* final, or still waits for the partner's FAIL, is that run.           *)
StuckExplained ==
    (Terminal /\ (~Final("A") \/ ~Final("B") \/ WaitsForFail("A") \/ WaitsForFail("B")))
        => KnownStuckRun

(* Order of accepts: a device accepts a partner GAP_VALUE only once it    *)
(* holds what the GAP_VALUE check reads (spec 2.3, F8b): the partner       *)
(* SEED_HASH, SALT, REC_HASH and SEED_VALUE, and its own SALT and          *)
(* SEED_VALUE. (A partner SEED_VALUE after the partner SEED_HASH is the    *)
(* receive guard in Expects, so it is not restated.)                       *)
AcceptOrder ==
    \A d \in Devices : \A m \in accepted[d] :
        m.tag = "GAP_VALUE" =>
            /\ \A t \in {"SEED_HASH", "SALT", "REC_HASH", "SEED_VALUE"} :
                   HasAccepted(d, m.k, t)
            /\ HasSigned(d, m.k, "SALT")
            /\ HasSigned(d, m.k, "SEED_VALUE")

(* The partner message a message answers (spec 2.3, "answers" column), *)
(* as <<tag, attempt>>; tag "none" when it answers nothing.             *)
AnswerOf(m) ==
    CASE m.tag = "SEED_HASH" /\ m.k = 1 -> <<"FAIL", 0>>
      [] m.tag = "SALT"       -> <<"SEED_HASH", m.k>>
      [] m.tag = "TIME"       -> <<"SALT", m.k>>
      [] m.tag = "REC_HASH"   -> IF m.from = "A" THEN <<"SALT", m.k>>
                                                ELSE <<"TIME", m.k>>
      [] m.tag = "SEED_VALUE" -> <<"REC_HASH", m.k>>
      [] m.tag = "GAP_HASH"   -> <<"SEED_VALUE", m.k>>
      [] m.tag = "GAP_VALUE"  -> <<"GAP_HASH", m.k>>
      [] OTHER                -> <<"none", m.k>>

(* The sender side of the peer check (spec 2.1): when a device signs a    *)
(* message, it has accepted the partner message that message answers.     *)
(* Receivers in this model do not run the peer check; this shows it would *)
(* pass between honest devices. Accepts only grow, so a state invariant   *)
(* is enough.                                                             *)
AnswersHeld ==
    \A m \in signed :
        LET a == AnswerOf(m) IN
        a[1] = "none" \/ HasAccepted(m.from, a[2], a[1])

(* With no fault at all, a run that stops ends on the verdict of a pair:  *)
(* both devices hold both GAP_VALUEs for the last attempt in their log.  *)
(* Only meaningful with every fault switch off.                          *)
EndsWithPair ==
    Terminal => \A d \in Devices : HoldsPair(d, LogAttempt(d))

(* Reach checks: each must be violated, to show the state is reachable. *)
KnownStuckRunNeverHappens == ~(Terminal /\ KnownStuckRun)
KnownStuckRunOnRetryNeverHappens ==
    ~(Terminal /\ KnownStuckRun /\ attempt["A"] = 1 /\ attempt["B"] = 1)
(* The link closed after one device got near and before the other got *)
(* the last GAP_VALUE. Allowed by the spec (FP5).                       *)
NoNearBesideIncomplete ==
    ~(~linkUp /\ \E d \in Devices :
          Outcome(d) = "near" /\ Outcome(Partner(d)) = "incomplete")
NoNearAfterRetry == ~(attempt["A"] = 1 /\ attempt["B"] = 1
                      /\ Outcome("A") = "near" /\ Outcome("B") = "near")
=============================================================================
