#!/bin/bash
# Builds and installs RawRec with the plain SDK tools, no Gradle. Needs the phone on USB debugging.
set -e
A=${ANDROID_HOME:-$HOME/Library/Android/sdk}; BT=$A/build-tools/36.0.0; P=$A/platforms/android-36/android.jar
export JAVA_HOME=$(/usr/libexec/java_home -v 21); export PATH=$JAVA_HOME/bin:$PATH
H=$(cd "$(dirname "$0")" && pwd); O=$(mktemp -d)
mkdir -p $O/cls $O/dex
javac -source 11 -target 11 -Xlint:-options -cp "$P" -d $O/cls $H/src/dev/enconomy/rawrec/*.java
$BT/d8 --lib "$P" --min-api 24 --output $O/dex $(find $O/cls -name '*.class')
$BT/aapt2 link -o $O/u.apk -I "$P" --manifest $H/AndroidManifest.xml
(cd $O/dex && zip -q $O/u.apk classes.dex)
$BT/zipalign -f 4 $O/u.apk $O/a.apk
$BT/apksigner sign --ks $HOME/.android/debug.keystore --ks-pass pass:android --key-pass pass:android --out $O/rawrec.apk $O/a.apk
$A/platform-tools/adb install -r -g $O/rawrec.apk
$A/platform-tools/adb shell am start -n dev.enconomy.rawrec/.Main
