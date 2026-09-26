#!/bin/bash
# Path (b)/(c): run the NDK-built zkprove (links release libbb-external.a via bbapi) on the attached Android phone.
# usage: run_zkprove.sh prove [A|B]     proves from the laptop-made witness (phone.gz / phoneB.gz)
#        run_zkprove.sh full  [A|B]     ACVM witness on the phone from Prover_A.toml / Prover_B.toml, then prove
# Pulls proof + public_inputs and verifies them on the laptop with the team vk (bb 5.0.0-nightly.20260522).
set -e
MODE=${1:-prove}; ROLE=${2:-A}
Z=$HOME/.enconomy/zk; A=$Z/android; P=$Z/optA/noir/phone
BIN=$A/target/aarch64-linux-android/release/zkprove; LBB=$A/rel50/lap/bb; VK=$P/vk/vk
if [ $MODE = full ]; then IN=$P/Prover_$ROLE.toml; REMOTE_IN=Prover_$ROLE.toml
else IN=$P/target/phone.gz; [ $ROLE = B ] && IN=$P/target/phoneB.gz; REMOTE_IN=w_$ROLE.gz; fi
D=/data/local/tmp/zk; OUT=$A/runs/$(date +%m%d_%H%M%S)_zkprove_${MODE}_$ROLE; mkdir -p $OUT
adb get-state >/dev/null
{ adb shell getprop ro.product.model; adb shell head -3 /proc/meminfo; } | tee $OUT/device.txt
adb shell mkdir -p $D/crs
push() { adb shell "[ -f $2 ] && [ \$(stat -c %s $2) = $(stat -f %z $1) ]" 2>/dev/null || adb push $1 $2; }
adb push $BIN $D/zkprove >/dev/null
push $P/target/phone.json $D/phone.json
push $IN $D/$REMOTE_IN
push $VK $D/vk
push $HOME/.bb-crs/bn254_g1.dat $D/crs/bn254_g1.dat
adb shell chmod 755 $D/zkprove
adb shell "cd $D && rm -rf out_z && ./zkprove $MODE phone.json $REMOTE_IN crs/bn254_g1.dat vk out_z" 2>&1 | tee $OUT/prove.log
adb pull $D/out_z/proof $OUT/proof >/dev/null; adb pull $D/out_z/public_inputs $OUT/public_inputs >/dev/null
ls -l $OUT
$LBB verify -k $VK -p $OUT/proof -i $OUT/public_inputs -t evm && echo "LAPTOP_VERIFY_OK (team vk, bb 5.0.0-nightly.20260522)" | tee -a $OUT/prove.log
