#!/bin/bash
# TLC on the pairing model.
#   ./run.sh Safety     check one config (Safety.cfg), print TLC's output
#   ./run.sh all        check every config, one line each, and compare with the expected result:
#                       the checks pass, the reach checks and the mutants fail on the named property.
# Needs Java 11 or newer and tla2tools.jar v1.7.4 at $TLA2TOOLS or ~/tla/tla2tools.jar.
# TLC_HEAP sets the Java heap (default 4g). Configs that must pass run with every core.
# Configs that must fail run with one worker. For an invariant or action property that
# fails, the count and the run TLC prints are then the same every time. For Liveness they
# are not: TLC checks liveness on a timer, so the count and the run depend on speed and load.
set -uo pipefail
cd "$(dirname "$0")"
JAR=${TLA2TOOLS:-$HOME/tla/tla2tools.jar}
HEAP=${TLC_HEAP:-4g}
[ -f "$JAR" ] || { echo "no tla2tools.jar at $JAR (set TLA2TOOLS)" >&2; exit 1; }

# -deadlock: a finished session has no next step, which is not an error here.
# tlc <config> <workers>
tlc() {
  java -Xmx"$HEAP" -XX:+UseParallelGC -cp "$JAR" tlc2.TLC -workers "$2" -deadlock \
    -cleanup -metadir "states/$1" -config "$1.cfg" Pairing.tla
}
workers_for() { [ "$(expected "$1")" = pass ] && echo auto || echo 1; }

# config | expected: "pass", or a line TLC prints when it finds the expected violation
EXPECT='Safety|pass
Live|pass
Stuck|pass
NoFault|pass
MutantAnswerAfterGapValueAgreement|pass
MutantNextAttemptWithoutPartnerFailAgreement|pass
LiveWithTimeouts|Temporal properties were violated
LiveWithClose|Temporal properties were violated
LiveWithLateLocalFail|Temporal properties were violated
KnownStuckRun|Invariant KnownStuckRunNeverHappens is violated
KnownStuckRunOnRetry|Invariant KnownStuckRunOnRetryNeverHappens is violated
NearAfterRetry|Invariant NoNearAfterRetry is violated
NearBesideIncomplete|Invariant NoNearBesideIncomplete is violated
MutantAnswerAfterGapValue|Invariant StuckExplained is violated
MutantTimeoutAfterGapValue|Invariant Agreement is violated
MutantTimeoutAfterGapValueNearStays|Action property NearStays is violated
MutantNextAttemptWithoutFails|Temporal properties were violated
MutantNextAttemptWithoutPartnerFail|Invariant StuckExplained is violated
MutantNextAttemptWithoutPartnerFailAnswers|Invariant AnswersHeld is violated
MutantBCombinesOwnFirst|Invariant Agreement is violated
MutantSignAfterFail|Invariant Agreement is violated
MutantGapValueWithoutPartnerGapHash|Invariant AcceptOrder is violated'
expected() { printf '%s\n' "$EXPECT" | awk -F'|' -v c="$1" '$1 == c { print $2 }'; }

cfg=${1:?usage: run.sh <config name, e.g. Safety> | all}
if [ "$cfg" != all ]; then
  [ -f "$cfg.cfg" ] || { echo "no $cfg.cfg" >&2; exit 1; }
  tlc "$cfg" "$(workers_for "$cfg")"
  exit $?
fi

mkdir -p logs
bad=0
printf '%-46s %-6s %12s %6s %8s\n' config result distinct depth seconds
while IFS='|' read -r name want; do
  start=$(date +%s)
  tlc "$name" "$(workers_for "$name")" > "logs/$name.out" 2>&1
  secs=$(( $(date +%s) - start ))
  out="logs/$name.out"
  states=$(grep -Eo '[0-9,]+ distinct states found' "$out" | tail -1 | grep -Eo '^[0-9,]+' | tr -d ,)
  depth=$(grep -Eo 'depth of the complete state graph search is [0-9]+' "$out" | grep -Eo '[0-9]+$')
  if grep -q 'No error has been found' "$out"; then got=pass
  elif grep -q '^Error:' "$out"; then got=fail
  else got=broken
  fi
  if [ "$want" = pass ]; then ok=$([ "$got" = pass ] && echo yes || echo no)
  else ok=$([ "$got" = fail ] && grep -qF "$want" "$out" && echo yes || echo no)
  fi
  [ "$ok" = yes ] || bad=1
  printf '%-46s %-6s %12s %6s %8s %s\n' "$name" "$got" "${states:--}" "${depth:--}" "$secs" \
    "$([ "$ok" = yes ] && echo as-expected || echo "NOT AS EXPECTED, see $out")"
done <<< "$EXPECT"
exit $bad
