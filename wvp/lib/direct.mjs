// Direct login: what the wallet signs and what K signs. Same file in the extension and the site, so they can't disagree.
const enc = new TextEncoder();
const b64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export const NAME_URN = "urn:wvp:ens:", THUMB_URN = "urn:ietf:params:oauth:jwk-thumbprint:sha-256:";
export const thumbprint = async (jwk) => b64u(await crypto.subtle.digest("SHA-256", enc.encode(JSON.stringify({ crv: jwk.crv, kty: jwk.kty, x: jwk.x, y: jwk.y }))));
// The readable line in the wallet prompt.
export const directStatement = (name, address, thumb, expIso) => `Approve browser key ${thumb} to log in to websites as ${name} and ${address}, or anonymously, until ${expIso}. No other use.`;
// What K signs to fetch its credential: the issuer's fresh one-time nonce. Only the holder of K can answer it, so a site that saw the wallet signature can't.
export const issueBytes = (issuerOrigin, nonce) => enc.encode(JSON.stringify(["wvp-issue-v1", issuerOrigin, nonce]));
// What K signs at login. The tag keeps this from meaning anything else. `origin` comes from the browser, never from the page.
export const loginBytes = (origin, challenge, now, claim) => enc.encode(JSON.stringify(["wvp-direct-login-v1", origin, challenge, now, claim]));
