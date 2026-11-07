// LOCAL TABLE ONLY. Points a name at a new address by editing the demo's JSON file. No chain, no cold key, nothing is signed.
// Usage: node demo/repoint.mjs alice.eth 0xNEW_ADDRESS
import { readFileSync, writeFileSync, renameSync, existsSync } from "node:fs";
import { isAddress } from "viem";
import { parseIdentifier } from "../lib/identifier.mjs";
import { TABLE_FILE } from "./lib/table.mjs";
const [typed, address] = process.argv.slice(2);
const id = parseIdentifier(typed);
if (id?.kind !== "name" || !isAddress(address ?? "")) { console.error("Usage: node demo/repoint.mjs alice.eth 0xNEW_ADDRESS"); process.exit(2); }
if (!existsSync(TABLE_FILE)) { console.error(`LOCAL TABLE: no table at ${TABLE_FILE}. Start the demo first.`); process.exit(1); }
const table = JSON.parse(readFileSync(TABLE_FILE, "utf8"));
const old = table[id.claim] ?? "(not set)";
table[id.claim] = address;
// Rename, so a site reading at this moment never sees half a file.
writeFileSync(`${TABLE_FILE}.new`, JSON.stringify(table, null, 2));
renameSync(`${TABLE_FILE}.new`, TABLE_FILE);
console.log(`LOCAL TABLE: ${id.claim} ${old} -> ${address}. No chain, no cold key.`);
