#!/bin/sh
# Throwaway Chrome profile for the demo. --ignore-certificate-errors is for this profile only (self-signed cert on 127.0.0.1).
here="$(cd "$(dirname "$0")/.." && pwd)"
exec "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="$here/.run/profile" \
  --no-first-run --no-default-browser-check \
  --remote-debugging-port=9333 \
  --enable-features=EmailVerificationProtocol \
  --host-resolver-rules="MAP tawago.test 127.0.0.1:8443, MAP recover.tawago.test 127.0.0.1:8443, EXCLUDE localhost" \
  --dns-txt-resolver-url-prefix="https://tawago.test/dns?name=" \
  --ignore-certificate-errors \
  --auto-grant-email-verification-permission-for-testing \
  "$@" https://tawago.test/login https://recover.tawago.test/
