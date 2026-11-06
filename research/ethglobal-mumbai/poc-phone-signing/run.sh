#!/bin/sh
# Re-run everything that runs on a laptop. No network except gradle/maven deps, no keys kept.
set -e
cd "$(dirname "$0")"
swiftc -O ios/sign_digest.swift -o "${TMPDIR:-/tmp}/pop_sign_digest"
"${TMPDIR:-/tmp}/pop_sign_digest" 64 > vectors/macos-seckey.json
(cd jvm-test && JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gradlew test :android-compile:compileKotlin --console=plain -q)
node noble-check.cjs
cd ../../.. && git apply --check research/ethglobal-mumbai/poc-phone-signing/patch/app.patch && echo "patch applies to app/"
