#!/bin/bash
# One-shot iPhone (iOS 16, USB) prove run: build, sign, install, launch, pull, verify, restore pop app.
#   ./run.sh [phone|phone_opt] [extra env, e.g. "BB_SLOW_LOW_MEMORY=1 HARDWARE_CONCURRENCY=2"]
# bb v5.0.0 (release lib + darwin CLI in ~/.enconomy/zk/ios/v500). v4.4.0-nightly cannot parse nargo beta.22 ACIR.
# No Apple ID in Xcode -> no new bundle id possible; we sign as com.enconomy.pop with the existing
# free-team profile, which REPLACES the pop app; pop.app backup is reinstalled at the end.
set -euo pipefail
C=${1:-phone}; ENVS="ZK_CIRCUIT=$C ${2:-}"
H=$(cd "$(dirname "$0")" && pwd); Z=~/.enconomy/zk/ios; B=$Z/v500/barretenberg-arm64-darwin/bb
PROF=~/Library/Developer/Xcode/UserData/Provisioning\ Profiles/0ddf89f0-295b-474d-a57f-518ad6904eb2.mobileprovision
ID=BF21AD823AA9A452B62CC6FED9835C05E6EC22B2
D=$(idevice_id -l | head -1); [ -n "$D" ] || { echo "no iPhone on USB"; exit 1; }
[ -f $Z/inputs/$C.req.msgpack ] || python3 $H/zkio.py prep $Z/inputs
cd $H && xcodegen generate -q
xcodebuild -project ZkBench.xcodeproj -scheme ZkBench -configuration Release -sdk iphoneos -arch arm64 \
  -derivedDataPath build/dev PRODUCT_BUNDLE_IDENTIFIER=com.enconomy.pop CODE_SIGNING_ALLOWED=NO build -quiet
A=$H/build/dev/Build/Products/Release-iphoneos/ZkBench.app
security cms -D -i "$PROF" > /tmp/zk_prof.plist
/usr/libexec/PlistBuddy -x -c "Print :Entitlements" /tmp/zk_prof.plist > /tmp/zk_ent.plist
cp "$PROF" $A/embedded.mobileprovision
codesign -f -s $ID --entitlements /tmp/zk_ent.plist $A
ios-deploy -i $D -b $A >/dev/null
N0=$(ios-deploy -i $D --bundle_id com.enconomy.pop --download=/Documents/log.txt --to /tmp/zk_dl >/dev/null 2>&1; grep -c '| end$' /tmp/zk_dl/Documents/log.txt 2>/dev/null || echo 0)
ios-deploy -i $D -m -b $A --justlaunch --envs "$ENVS" >/dev/null
for i in $(seq 1 60); do sleep 10; rm -rf /tmp/zk_dl
  ios-deploy -i $D --bundle_id com.enconomy.pop --download=/Documents/log.txt --to /tmp/zk_dl >/dev/null 2>&1 || true
  [ "$(grep -c '| end$' /tmp/zk_dl/Documents/log.txt)" -gt "$N0" ] && break; done
R=$Z/runs/$(date +%H%M%S)_$C; mkdir -p $R; cp /tmp/zk_dl/Documents/log.txt $R/
LC_ALL=C grep -a RESULT $R/log.txt | tail -1 || echo "no RESULT: likely jetsam, see $R/log.txt"
if ios-deploy -i $D --bundle_id com.enconomy.pop --download=/Documents/$C.resp.msgpack --to $R/dl >/dev/null 2>&1; then
  python3 $H/zkio.py decode $R/dl/Documents/$C.resp.msgpack $R && $B verify -t evm -k $R/vk -p $R/proof -i $R/public_inputs
fi
ios-deploy -i $D -b $Z/popbackup/pop.app >/dev/null && echo "pop app restored"
