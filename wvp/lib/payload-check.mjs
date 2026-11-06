// What the issuer checks on the exact text it is about to sign. See the PRECONDITION note in upstream's jwt.circom.
//
// The circuit only proves that a disclosure's digest occurs somewhere in the decoded payload. So nothing else in the
// payload may look like a digest. The SDK has a similar check, but it runs on the holder's machine, and it only looks
// at the digests the holder hands it. A cheater's digest is one the issuer never saw, so this check is about shape:
// any run of base64url characters 43 or longer must be K's x, K's y, or one of our own digests. Nothing else.
const count = (s, needle) => s.split(needle).length - 1;

export function payloadProblem(json, { x, y, digests }) {
  for (const a of ['"x":"', '"y":"', '"_sd":[']) if (count(json, a) !== 1) return `${a} occurs ${count(json, a)} times, want 1`;
  if (!json.includes(`"x":"${x}"`)) return '"x":" is not directly before K\'s x';
  if (!json.includes(`"y":"${y}"`)) return '"y":" is not directly before K\'s y';
  const start = json.indexOf('"_sd":[') + 7, end = json.indexOf("]", start);
  if (end < 0) return "_sd array never closes";
  const inSd = json.slice(start, end);
  for (const d of digests) {
    if (count(json, d) !== 1) return `digest ${d} occurs ${count(json, d)} times, want 1`;
    if (!inSd.includes(`"${d}"`)) return `digest ${d} is outside _sd`;
  }
  const runs = json.match(/[A-Za-z0-9_-]{43,}/g) ?? [];
  const allowed = [x, y, ...digests];
  for (const r of runs) if (!allowed.includes(r)) return `signed text holds a digest-shaped string that isn't K or an _sd entry: ${r}`;
  if (runs.length !== allowed.length) return `found ${runs.length} digest-shaped strings, want ${allowed.length}`;
  return null;
}
