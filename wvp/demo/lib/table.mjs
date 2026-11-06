// The demo's LOCAL TABLE of ENS names. demo/servers.mjs writes it, the sites read it on every lookup, demo/repoint.mjs changes it.
import { tmpdir } from "node:os";
import { join } from "node:path";
export const TABLE_FILE = process.env.WVP_ENS_TABLE ?? join(tmpdir(), "wvp-demo-ens-table.json");
