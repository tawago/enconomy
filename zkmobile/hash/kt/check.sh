#!/usr/bin/env bash
# JVM check of the Kotlin commonMain ports (Bn254Fr, Poseidon2Bn, OaHash) against vectors.json + the real fixture.
# Uses the Kotlin 2.2.20 compiler jars from the gradle cache (no kotlinc needed). Output under ~/.enconomy/zk/hash/kt.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); root=$here/../../..
C=~/.gradle/caches/modules-2/files-2.1; j(){ find $C/$1/$2 -name "$2-$3.jar" | head -1; }
STD=$(j org.jetbrains.kotlin kotlin-stdlib 2.2.20)
CP=$(j org.jetbrains.kotlin kotlin-compiler-embeddable 2.2.20):$STD:$(j org.jetbrains.kotlin kotlin-script-runtime 2.2.20):$(j org.jetbrains.kotlin kotlin-daemon-embeddable 2.2.20):$(j org.jetbrains.intellij.deps trove4j 1.0.20200330):$(j org.jetbrains.kotlin kotlin-reflect 2.0.21):$(j org.jetbrains.kotlinx kotlinx-coroutines-core-jvm 1.10.2):$(find $C/org.jetbrains/annotations -name 'annotations-23*.jar' | grep -v sources | head -1)
K=$root/app/composeApp/src/commonMain/kotlin/com/enconomy/pop/zk
out=$HOME/.enconomy/zk/hash/kt; mkdir -p "$out"
java -cp "$CP" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-reflect -no-stdlib -nowarn -cp "$STD" -d "$out" \
  $K/Bn254Fr.kt $K/Poseidon2Bn.kt $K/Poseidon2BnParams.kt $K/OaHash.kt $here/Check.kt
java -cp "$out:$STD" com.enconomy.pop.zk.CheckKt $here/../vectors.json \
  $HOME/.enconomy/zk/hash/noirws/helper/Prover.toml $here/../fixture_vectors.json
