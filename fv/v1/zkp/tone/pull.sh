#!/bin/bash
# Pull the newest RawRec WAV from the phone and score it. Run from anywhere. Writes to the folder you run it in.
set -e
A=${ANDROID_HOME:-$HOME/Library/Android/sdk}/platform-tools/adb
R=$(cd "$(dirname "$0")/../../../.." && pwd)
D=/sdcard/Android/data/dev.enconomy.rawrec/files
F=$($A shell ls -t $D | tr -d '\r' | grep '\.wav$' | head -1)
[ -n "$F" ] || { echo "no recording on the phone yet"; exit 1; }
$A pull "$D/$F" . >/dev/null
$A shell cat "$D/$F.txt"
$R/server/.venv/bin/python $R/fv/v1/zkp/tone/tone_test.py score "$F"
