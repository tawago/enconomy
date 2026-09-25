// Build a valid input for binding.circom from the real JB result of session
// c72ce4b6 (30 cm): flight 30.0 cm, B_at_A score 51.9 %. Keys are throwaway.
import { buildEddsa, buildPoseidon } from "circomlibjs";
import { readFileSync, writeFileSync } from "fs";
import { randomBytes } from "crypto";

const eddsa = await buildEddsa();
const P = await buildPoseidon();
const F = P.F;
const h = (xs) => P(xs.map((x) => BigInt(x)));
const s = (e) => F.toObject(e).toString();

const out = process.argv[2];
const session = JSON.parse(readFileSync(process.argv[3], "utf8"));
const res = JSON.parse(readFileSync(process.argv[4], "utf8"));
const r0 = res.probes.JB.rounds[0];

const seed = BigInt("0x" + session.seed_hex) % F.p;
const salt = BigInt("0x" + randomBytes(31).toString("hex"));
const sessionCommit = h([seed, salt]);

const key = () => { const k = randomBytes(32); return { k, pub: eddsa.prv2pub(k) }; };
const A = key(), B = key(), M = key();
const sign = (who, m) => { const sg = eddsa.signPoseidon(who.k, m); return [s(sg.R8[0]), s(sg.R8[1]), sg.S.toString()]; };

const timestamp = 1790300000;
const flight = Math.round(r0.flight_cm * 10);                 // mm
const drr = Math.round((r0.drr_AB_db ?? 0) * 100) + 10000;     // 0.01 dB + offset
const score = Math.round(r0.arrivals.B_at_A.right_pct * 100);  // 0.01 %

const pk = (w) => [F.toObject(w.pub[0]), F.toObject(w.pub[1])];
const [ax, ay] = pk(A), [bx, by] = pk(B), [mx, my] = pk(M);
const msg = h([F.toObject(sessionCommit), ax, ay, bx, by, timestamp, flight, drr, score, 0]);
const att = h([F.toObject(sessionCommit), ax, ay, bx, by, timestamp]);

const input = {
  sessionCommit: s(sessionCommit),
  measurerKeyHash: s(h([mx, my])),
  maxFlight: 450, minDrr: 10000 - 1000, minScore: 1000,
  nullifier: s(h([F.toObject(sessionCommit), ax, bx])),
  seed: seed.toString(), salt: salt.toString(), timestamp, flight, drr, score,
  pkA: [ax.toString(), ay.toString()], sigA: sign(A, att),
  pkB: [bx.toString(), by.toString()], sigB: sign(B, att),
  pkM: [mx.toString(), my.toString()], sigM: sign(M, msg),
};
writeFileSync(out, JSON.stringify(input, null, 1));
console.log({ flight_mm: flight, drr, score });
