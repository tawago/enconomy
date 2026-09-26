#!/bin/bash
# Path (a): run the release arm64-linux (glibc) bb CLI on Android through a bundled Debian glibc 2.36 loader.
# bb = v5.0.0-nightly.20260522 from github.com/AztecProtocol/barretenberg releases; its darwin build is
# byte-identical to the ZK team's bb, so the team's vk (and PhoneVerifier.sol) apply unchanged.
# usage: run_glibc_bb.sh [ROLE=A|B] [EXTRA bb flags...]      needs one adb device attached
set -e
ROLE=${1:-A}; shift || true; EXTRA="$*"
Z=$HOME/.enconomy/zk; A=$Z/android; P=$Z/optA/noir/phone
BB=$A/rel50/linux/bb; LBB=$A/rel50/lap/bb; G=$A/glibc; VK=$P/vk/vk
W=$P/target/phone.gz; [ "$ROLE" = B ] && W=$P/target/phoneB.gz
D=/data/local/tmp/zk; OUT=$A/runs/$(date +%m%d_%H%M%S)_glibc_$ROLE; mkdir -p $OUT
adb get-state >/dev/null
{ adb shell getprop ro.product.model; adb shell head -3 /proc/meminfo; } | tee $OUT/device.txt
adb shell mkdir -p $D/crs $D/out
push() { adb shell "[ -f $2 ] && [ \$(stat -c %s $2) = $(stat -f %z $1) ]" 2>/dev/null || adb push $1 $2; }
push $BB $D/bb
push $G/ld-linux-aarch64.so.1 $D/ld-linux-aarch64.so.1
push $G/libc.so.6 $D/libc.so.6
push $P/target/phone.json $D/phone.json
push $W $D/w_$ROLE.gz
push $VK $D/vk
push $HOME/.bb-crs/bn254_g1.dat $D/crs/bn254_g1.dat
adb shell chmod 755 $D/bb $D/ld-linux-aarch64.so.1
adb shell "cd $D && HOME=$D ./ld-linux-aarch64.so.1 --library-path $D ./bb --version"
# wall time from date +%s%N; peak memory = max VmHWM polled every 0.3 s from /proc/<bb pid>/status
adb shell "cd $D && rm -f out/proof out/public_inputs hwm.log; (while true; do for p in \$(pgrep -f 'bb prove'); do grep VmHWM /proc/\$p/status >> hwm.log 2>/dev/null; done; sleep 0.3; done) & M=\$!; s=\$(date +%s%N); HOME=$D ./ld-linux-aarch64.so.1 --library-path $D ./bb prove -b phone.json -w w_$ROLE.gz -k vk -o out -t evm -c $D/crs -v $EXTRA; rc=\$?; e=\$(date +%s%N); kill \$M; echo WALL_MS=\$(( (e-s)/1000000 )) rc=\$rc; echo PEAK_\$(sort -k2 -n hwm.log | tail -1)" 2>&1 | tee $OUT/prove.log
adb pull $D/out/proof $OUT/proof; adb pull $D/out/public_inputs $OUT/public_inputs
ls -la $OUT
$LBB verify -k $VK -p $OUT/proof -i $OUT/public_inputs -t evm && echo "LAPTOP_VERIFY_OK (team vk, bb 5.0.0-nightly.20260522)" | tee -a $OUT/prove.log
