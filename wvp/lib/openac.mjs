// Loads the patched SDK (prover/sdk-q1.patch adds external signature support).
import { pathToFileURL } from "node:url";
import { thirdParty } from "./third-party.mjs";

export const sdk = await import(pathToFileURL(thirdParty("sdk-q1/dist/index.js")).href);
