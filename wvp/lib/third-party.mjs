// Where the third-party files live. They aren't in this repo. See prover/README.md.
import { existsSync } from "node:fs";
import { join } from "node:path";

export function thirdParty(...parts) {
  const base = process.env.WVP_THIRD_PARTY;
  if (!base) throw new Error("Set WVP_THIRD_PARTY to the folder that holds keys/, sdk-q1/, p2-threads/ and p2-cached/. prover/README.md says how to make it.");
  const p = join(base, ...parts);
  if (!existsSync(p)) throw new Error(`WVP_THIRD_PARTY has no ${join(...parts)}. prover/README.md says how to make it.`);
  return p;
}
