#!/bin/sh
# Throwaway Chrome profile for the live EVP test. Local only.
# --ignore-certificate-errors is for this temp profile only (self-signed cert on 127.0.0.1).
here="$(cd "$(dirname "$0")" && pwd)"
prof="$here/tmp/profile"
mkdir -p "$prof"
set -- \
  --user-data-dir="$prof" \
  --no-first-run --no-default-browser-check \
  --remote-debugging-port=9333 \
  --enable-features=EmailVerificationProtocol \
  --host-resolver-rules="MAP tawago.test 127.0.0.1:8443, MAP recover.tawago.test 127.0.0.1:8443, EXCLUDE localhost" \
  --dns-txt-resolver-url-prefix="https://tawago.test/dns?name=" \
  --ignore-certificate-errors \
  "$@" about:blank
printf '%s\n' "$@" > "$here/tmp/chrome-argv.txt"
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" "$@"
