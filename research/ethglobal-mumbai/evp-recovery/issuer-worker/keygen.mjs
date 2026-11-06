// Prints a fresh P-256 private JWK for the test issuer. Test key only.
import { webcrypto as C } from "node:crypto";
const kp = await C.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
const { kty, crv, x, y, d } = await C.subtle.exportKey("jwk", kp.privateKey);
console.log(JSON.stringify({ kty, crv, x, y, d }));
