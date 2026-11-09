import ServerFv.V7Replay

/-!
# V7 row 1: a NEAR record replays to NEAR

Gap 5, V7, the NEAR row. Take a reachable document whose final record says `NEAR`. Re-running
`verify_record` (`verdict.py:168-189`) on that record, as `toRR` reads it, returns `NEAR` with the
record's own flight, no reason and no `by`.

**What it pins.** The whole `CombineOut` the replay returns, field by field, against the stored
record: `flight_cm` equals `rc.flight_cm`, verdict `NEAR`, reason none, `by_` none.

**What it does not pin.** Rows 2-4 (`too_far`, `impossible_flight`, `self_timestamp_mismatch`) and
row 5 (missing transcript) are other chunks. Record fields `verify_record` never reads (`half`,
`sample_rate`, `popt`, `attempts`, times) are not compared. Hex decoding of the nonce and keys is
not modeled (see `V7Bridge`).
-/

namespace ServerFv
namespace Machine

variable {B D : Type} [DecidableEq B] [DecidableEq D]

omit [DecidableEq D] in
/-- **The shape of a NEAR result.** If `combine` returns a value whose verdict is `NEAR`, that value
came from the last branch (`verdict.py:165-167`): reason none, `by_` none, and a flight strictly
between -20 and 60 cm. The two self-check branches have no verdict, so they cannot give `NEAR`.
It says nothing about which transcripts or calibration led there. -/
theorem combine_near_shape {ta tb : Transcript B} {cal : Option (Role → Option ℤ)}
    {out : CombineOut} (h : combine ta tb cal = .ok out) (hv : out.verdict = some .NEAR) :
    out.reason = none ∧ out.by_ = none ∧ ∃ f, out.flight_cm = some f ∧ -20 < f ∧ f < 60 := by
  unfold combine at h
  split_ifs at h
  all_goals (cases h)
  all_goals try (exfalso; simp at hv; done)
  generalize flight_exact ta.half ta.sample_rate tb.half tb.sample_rate = f at hv ⊢
  obtain ⟨-, -, hn, hall⟩ := V2 f
  rcases hall with hd | hd | hd
  · simp [hd] at hv
  · simp [hd] at hv
  · exact ⟨by simp [hd], rfl, f, rfl, hn.1 hd⟩

/-- **V7 row 1, NEAR.** Take a reachable document `s` whose final record `rc` says `NEAR`. Then
`toRR e rc` exists and `verify_record` on it returns exactly
`⟨rc.flight_cm, some NEAR, none, none⟩`: the record's own flight, verdict `NEAR`, no reason, no
`by`.

So an offline verifier that re-runs `verify_record` on a published NEAR record gets the same
verdict and the same flight the server wrote. It assumes nothing about `e` (no key injectivity).
It does not cover records with another verdict. -/
theorem V7_near {e : Env B D} {c : ℕ} {s : Doc B D} {rc : Record B D} (h : Reachable e c s)
    (hr : s.result = some rc) (hv : rc.verdict = .NEAR) :
    ∃ rr, toRR e rc = some rr ∧
      verify_record e.p rr = .ok ⟨rc.flight_cm, some .NEAR, none, none⟩ := by
  have hc : Core e c s := (M9 h).toCore
  have nf := hc.near rc hr hv
  have hall := nf.both
  simp only [all2, Bool.and_eq_true] at hall
  have hrc := hc.rec_eq rc hr
  have hpres : ∀ r, s.submitted r = true → rc.transcripts r ≠ none := by
    intro r hs
    have hsome := (hc.sub_iff r).1 hs
    rw [hrc]
    rcases ht : (s.per_role r).tx with _ | td
    · simp [ht] at hsome
    · simp [_record, ht]
  obtain ⟨rr, ta, tb, hrr, hsA, hsB, heq⟩ :=
    V7_replay_eq h hr (hpres .A hall.1) (hpres .B hall.2)
  obtain ⟨ta', tb', out, hsA', hsB', hcmb, hvo, hfl⟩ := nf.cmb
  rw [hsA] at hsA'; cases hsA'
  rw [hsB] at hsB'; cases hsB'
  obtain ⟨hrs, hby, -⟩ := combine_near_shape hcmb hvo
  refine ⟨rr, hrr, ?_⟩
  rw [heq, hcmb]
  obtain ⟨fl, vd, rs, by'⟩ := out
  simp only at hrs hby hvo hfl
  subst hrs hby hvo hfl
  rfl

end Machine
end ServerFv

#print axioms ServerFv.Machine.combine_near_shape
#print axioms ServerFv.Machine.V7_near
