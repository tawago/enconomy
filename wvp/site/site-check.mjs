// Site side. Recomputes the nonce from its own origin, compares the issuer key, and rejects for one named reason.
// The origin is fixed when the server starts, never read from a request.
import { bindNonce, SCHEMA, namedPolicy, hiddenPolicy } from "../lib/wvp.mjs";
import { canonicalProblem } from "../lib/bundle.mjs";

export function classify(error) {
  const e = String(error ?? "");
  if (e.includes("Statement binding mismatch (nonce)")) return "wrong_nonce";
  if (e.includes("Statement binding mismatch (policy)")) return "wrong_policy";
  if (e.includes("Shared commitment mismatch")) return "key_mismatch";
  if (e.includes("deserialization failed")) return "proof_malformed";
  if (e.includes("proof verification failed")) return "proof_invalid";
  return "other_error";
}

// The whole site check, without the challenge store.
export async function siteCheck({ openac, sdk, vks, trustedIssuer, origin, ctx, bundle }) {
  const t = performance.now();
  const done = (o) => ({ ...o, ms: Math.round(performance.now() - t) });
  const problem = canonicalProblem(bundle);
  if (problem) return done({ accepted: false, reason: "non_canonical", detail: problem });
  const nonce = bindNonce(origin, ctx.challenge);
  const compiled = sdk.compilePredicateExpression(ctx.name ? namedPolicy(ctx.name, ctx.now) : hiddenPolicy(ctx.now), SCHEMA);
  let r;
  try {
    r = await openac.verifyProof(bundle, vks, { nonce, predicates: compiled.predicates, logicExpression: compiled.logicExpression, claimNormalization: sdk.requiredNormalization(compiled) });
  } catch (e) {
    return done({ accepted: false, reason: e instanceof WebAssembly.RuntimeError ? "prover_crashed" : classify(e.message ?? e), detail: String(e.message ?? e).slice(0, 200), crashed: e instanceof WebAssembly.RuntimeError });
  }
  if (!r.valid) return done({ accepted: false, reason: classify(r.error), detail: r.error, verifyMs: r.verifyMs });
  if (r.issuerKey.jwk.x !== trustedIssuer.x || r.issuerKey.jwk.y !== trustedIssuer.y)
    return done({ accepted: false, reason: "wrong_issuer", detail: `proof's issuer x=${r.issuerKey.jwk.x}, this site trusts x=${trustedIssuer.x}`, verifyMs: r.verifyMs });
  if (r.expressionResult !== true) return done({ accepted: false, reason: "claim_false", detail: "proof is sound but the statement is false", verifyMs: r.verifyMs });
  return done({ accepted: true, reason: "ok", name: ctx.name, hiddenName: !ctx.name, verifyMs: r.verifyMs });
}
