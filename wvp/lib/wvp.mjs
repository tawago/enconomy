// Shared rules between issuer, holder and site. No secrets here.
import { createHash } from "node:crypto";
import { normalize } from "viem/ens";
import { nameDigest } from "./name-digest.mjs";

const sha256hex = (s) => createHash("sha256").update(s).digest("hex");

// The name slot's value. Moved out so the browser builds share the exact same code.
export { nameDigest };
export const normalizeName = (name) => normalize(name);

// nonce = hash(origin, challenge). Both holder and site compute this.
export const bindNonce = (origin, challenge) => sha256hex(JSON.stringify([origin, challenge]));

// Slot order the issuer always uses. A site only needs this, never a credential.
export const SCHEMA = [{ name: "name", index: 0 }, { name: "exp", index: 1 }];
export const namedPolicy = (name, now) => ({ all: [{ claim: "name", op: "==", value: nameDigest(name) }, { claim: "exp", op: ">=", value: now }] });
export const hiddenPolicy = (now) => ({ claim: "exp", op: ">=", value: now });

// RFC 7638 thumbprint of a P-256 JWK.
export const thumbprint = (jwk) => createHash("sha256")
  .update(JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x, y: jwk.y })).digest("base64url");

// The text the wallet signs. The issuer rebuilds this and compares, so nothing can be slipped in.
export const THUMB_URN = "urn:ietf:params:oauth:jwk-thumbprint:sha-256:";
export const NAME_URN = "urn:wvp:ens:";
