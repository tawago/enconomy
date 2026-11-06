import ServerFv.Machine
open ServerFv ServerFv.Machine ServerFv.Machine.Witness

def show1 : Resp ℕ ℕ → String
  | .created .. => "created"
  | .view v => s!"view st={repr v.state} att={v.attempt} seq={v.seq} res={v.result.isSome} nonce={v.nonce.isSome} err={repr v.error}"
  | .armMaterial a _ p o oc _ => s!"arm att={a} play={repr p.role} own={repr o.role} code={repr (oc.map (·.role))}"
  | .partnerBed pb pc _ => s!"partner role={repr pb.role} att={pb.attempt} code={repr (pc.map (·.role))}"
  | .accepted st a => s!"accepted {repr st} att={a}"
  | .record r => s!"record {repr r.verdict} reason={repr r.reason} flight={repr r.flight_cm} att={r.attempt} rows={r.attempts.length}"
  | .other => "other"
  | .error c x => s!"ERR {c} {repr x}"

def showDoc (s : Doc ℕ ℕ) : String :=
  s!"[st={repr s.state} att={s.attempt} seq={s.seq} rows={s.attempts.length} t0={repr s.t0_ms} fin={repr s.finished_ms} err={repr s.error} v={repr (s.result.map (·.verdict))} guest={repr s.guest_device_id}]"

def trace (name : String) (e : Env ℕ ℕ) (s0 : Doc ℕ ℕ) (l : List (ℕ × Req ℕ ℕ)) : IO (Doc ℕ ℕ) := do
  IO.println s!"== {name}"
  let mut s := s0
  for p in l do
    let (s', r) := step e (W p.1) p.2 s
    IO.println s!"  t={p.1}: {show1 r} {showDoc s'}"
    s := s'
  return s

def armR (d k : ℕ) (sr : ℤ := 48000) : Req ℕ ℕ := R d (.arm (.int k) (.int sr) (some 10) .null)
def badE (H : ℕ → Role → ℤ) : Env ℕ ℕ := { env H with b64d := fun n => if n = 999 then none else some n }
def Himp : ℕ → Role → ℤ := fun _ r => match r with | .A => -1000 | .B => 0
def upTo (n : ℕ) : List (ℕ × Req ℕ ℕ) := opening ++ [(n, armR 1 0), (n+1, armR 2 0)]

def main : IO Unit := do
  let _ ← trace "near" (env Hnear) start nearTrace
  let n ← trace "near result" (env Hnear) nearDoc [(4500, R 1 .result), (4501, R 2 .view), (4502, R 1 .abort), (4503, R 1 (.transcript 11 111)), (4504, R 1 (.commit 10 110)), (4505, R 1 (.fail_ (.int 0) (some .glitch)))]
  let _ ← trace "far" (env Hfar) start farTrace
  let _ ← trace "far result" (env Hfar) farDoc [(4500, R 1 .result)]
  let _ ← trace "retry then near" (env Hretry) start retry1Trace
  let _ ← trace "after retry, old things" (env Hretry) retry0Doc
    [(4500, R 1 (.transcript 11 111)), (4501, R 1 (.fail_ (.int 0) (some .glitch))), (4502, R 1 (.commit 10 110)),
     (4503, R 1 (.fail_ (.int 5) (some .glitch))), (4504, R 1 (.fail_ (.int (-1)) (some .glitch))),
     (4510, armR 1 0), (4511, armR 1 1), (4512, armR 2 1), (9000, R 1 (.commit 10 110)), (9001, R 1 (.transcript 11 111))]
  let _ ← trace "third attempt?" (env Himp) start (retry1Trace)
  let _ ← trace "too early + arm" (env Hnear) start (opening ++
     [(10, R 1 (.commit 10 110)), (10, armR 1 0), (10, armR 1 0), (10, armR 1 0 44100), (10, R 1 (.arm (.int 0) (.int 48000) (some 10) (.int 2))),
      (10, R 1 (.arm (.int 1) (.int 48000) (some 10) .null)), (10, R 1 (.arm .other (.int 48000) (some 10) .null)),
      (10, R 1 (.arm (.int 0) (.int 1) (some 10) .null)), (10, R 1 (.arm (.int 0) (.int 48000) (some 301) .null)),
      (10, R 1 (.arm (.int 0) (.int 48000) none .null)), (10, R 1 (.arm (.int 0) (.int 48000) (some 10) (.int 3))),
      (11, armR 2 0), (11, armR 1 0), (12, R 1 (.transcript 11 111)), (4210, R 1 (.commit 10 110)), (4211, R 1 (.commit 10 110)),
      (4212, R 1 (.commit 10 110)), (4213, R 1 (.commit 10 999)), (4214, R 1 (.commit 11 111)), (4215, R 2 (.commit 10 110)), (4216, R 1 .result)])
  let _ ← trace "bad transcript sig" (env Hnear) start (upTo 10 ++ [(4300, R 1 (.commit 10 110)), (4301, R 1 (.transcript 11 112)), (4302, R 2 .view), (4303, R 1 .result)])
  let _ ← trace "bad b64" (badE Hnear) start (upTo 10 ++ [(4300, R 1 (.commit 999 110)), (4300, R 1 (.commit 10 110)), (4301, R 1 (.transcript 999 111)), (4303, R 1 .result)])
  let _ ← trace "repeat transcript" (env Hnear) start (upTo 10 ++ [(4300, R 1 (.commit 10 110)), (4301, R 1 (.transcript 11 111)), (4302, R 1 (.transcript 11 111)), (4303, R 1 (.transcript 11 112)), (4304, R 1 (.fail_ (.int 0) (some .glitch))), (4305, R 2 .view)])
  let _ ← trace "fail variants" (env Hnear) start (opening ++ [(10, R 1 (.fail_ (.int 0) none)), (10, R 1 (.fail_ (.int 0) (some .too_far))), (10, R 1 (.fail_ .other (some .glitch))), (10, R 1 (.fail_ .null (some .glitch))), (10, R 1 (.fail_ (.int 1) (some .glitch))), (11, R 1 (.fail_ (.int 0) (some .glitch))), (12, R 2 (.fail_ (.int 1) (some .glitch))), (13, R 1 .result)])
  let _ ← trace "partner_mismatch final" (env Hnear) start (opening ++ [(10, R 2 (.fail_ (.int 0) (some .partner_mismatch))), (11, R 1 .result)])
  let _ ← trace "pairing errors" (env Hnear) start
     [(1, R 2 .view), (1, .api false (some 1) false (.join "t")), (1, .api false (some 2) false (.join "x")), (1, R 1 .confirm),
      (1, R 1 (.arm (.int 0) (.int 48000) (some 10) .null)), (1, R 1 .view), (1, R 1 .result), (1, .api true (some 2) false (.join "t")), (1, .api false none false (.join "t")), (1, .api false (some 2) true (.join "t")),
      (2, .api false (some 2) false (.join "T")), (3, .api false (some 3) false (.join "t")), (3, R 3 .view), (4, R 1 .confirm), (4, R 1 .confirm), (4, R 2 .view), (5, R 2 .confirm), (5, R 2 .confirm), (5, R 2 .view)]
  let _ ← trace "E1 edge" (env Hnear) start [(120000, .noauth_load), (120001, .noauth_load), (120002, .api false (some 2) false (.join "t")), (120003, R 1 .abort)]
  let _ ← trace "E2" (env Hnear) start (opening ++ [(600003, R 3 .view), (600004, R 1 .view)])
  let _ ← trace "E2 edge" (env Hnear) start (opening ++ [(600000, R 1 .view), (600001, R 3 .view)])
  let _ ← trace "E3 retry" (env Hnear) start (upTo 10 ++ [(4300, R 1 (.commit 10 110)), (4301, R 1 (.transcript 11 111)), (23011, .noauth_load), (23012, .noauth_load), (23012, R 2 .view)])
  let _ ← trace "E3 both silent then final" (env Hnear) start (upTo 10 ++ [(23012, R 3 .view), (30000, armR 1 1), (30001, armR 2 1), (53002, R 2 .view), (53003, R 2 .result)])
  let _ ← trace "E2 beats E3 with one tx" (env Hnear) start (upTo 590000 ++ [(594000, R 1 (.commit 10 110)), (594001, R 1 (.transcript 11 111)), (620000, R 1 .view)])
  let _ ← trace "abort live" (env Hnear) start (upTo 10 ++ [(20, R 2 .abort), (21, R 1 .abort), (22, R 1 .result)])
  IO.println "done"

#eval main
