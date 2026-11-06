// Byte layout of a serialized presentation for the 1k JWT + Show circuits.
// Format, from prover.ts: [u32le length][bytes] x (version, prepareProof, showProof, prepareInstance, showInstance).
//
// Found by reading Spartan2 d687dbb and by looking at real bundles:
// - Each instance blob is exactly the first bytes of its proof (the serialized `U`).
// - `U.blind_vars` is four entries of 45 bytes: [01][32-byte value][u32 1][u64 variable index].
//   Verify never reads them. The Prepare ones are the same in every presentation, so they link users.
//   The holder zeroes the values. The site insists on that exact form.
// - `U.num_shared, num_precommitted, num_rest` are three u64 counts just before those. Verify reads the counts from the
//   verifying key instead, so a change to their low 4 bytes passes. (A byte-flip sweep found this.) The site pins them.
export const NAMES = ["version", "prepareProof", "showProof", "prepareInstance", "showInstance"];
export const VERSION = "0.1.0";
export const SIZES = { prepareProof: 77815, showProof: 47399, prepareInstance: 34223, showInstance: 6287 };
export const BLIND = { prepareProof: { at: 33835, firstIndex: 0x0f0c14n }, showProof: { at: 1099, firstIndex: 0x4933n } };
export const ENTRY = 45;
export const COUNTS = { prepareProof: { at: 33810, values: [1024n, 0n, 1047552n] }, showProof: { at: 1074, values: [1024n, 0n, 31744n] } };

export function parseBundle(buf) {
  const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const out = {}; let o = 0;
  for (const n of NAMES) {
    if (o + 4 > buf.length) throw new Error(`truncated before ${n}`);
    const len = v.getUint32(o, true); o += 4;
    if (o + len > buf.length) throw new Error(`${n} runs past the end`);
    out[n] = { start: o, len }; o += len;
  }
  if (o !== buf.length) throw new Error(`${buf.length - o} trailing bytes`);
  return out;
}
export const slice = (buf, part) => buf.subarray(part.start, part.start + part.len);

function blindFormProblem(proof, { at, firstIndex }, wantZero) {
  for (let k = 0; k < 4; k++) {
    const e = Buffer.from(proof.subarray(at + k * ENTRY, at + (k + 1) * ENTRY));
    if (e[0] !== 1) return `blind entry ${k}: bad tag`;
    if (e.readUInt32LE(33) !== 1) return `blind entry ${k}: bad variable kind`;
    if (e.readBigUInt64LE(37) !== firstIndex + BigInt(k)) return `blind entry ${k}: bad variable index`;
    if (wantZero && e.subarray(1, 33).some((b) => b !== 0)) return `blind entry ${k}: value not zero`;
  }
  return null;
}

// Holder side: returns a copy with the four blind values zeroed in both proofs and both instances.
export function scrubBundle(input) {
  const buf = new Uint8Array(input);
  const p = parseBundle(buf);
  for (const [proofName, instName] of [["prepareProof", "prepareInstance"], ["showProof", "showInstance"]]) {
    for (const name of [proofName, instName]) {
      const bytes = slice(buf, p[name]);
      const problem = blindFormProblem(bytes, BLIND[proofName], false);
      if (problem) throw new Error(`scrub: ${name}: unexpected layout: ${problem}`);
      for (let k = 0; k < 4; k++) bytes.fill(0, BLIND[proofName].at + k * ENTRY + 1, BLIND[proofName].at + k * ENTRY + 33);
    }
  }
  return buf;
}

// Site side: null if the bundle has the one accepted form, else why not.
export function canonicalProblem(buf) {
  let p;
  try { p = parseBundle(buf); } catch (e) { return `bundle framing: ${e.message}`; }
  const ver = new TextDecoder().decode(slice(buf, p.version));
  if (ver !== VERSION) return `version ${JSON.stringify(ver)}`;
  for (const [n, want] of Object.entries(SIZES)) if (p[n].len !== want) return `${n} is ${p[n].len} bytes, want ${want}`;
  for (const [proofName, instName] of [["prepareProof", "prepareInstance"], ["showProof", "showInstance"]]) {
    const proof = slice(buf, p[proofName]), inst = slice(buf, p[instName]);
    if (!Buffer.from(proof.subarray(0, inst.length)).equals(Buffer.from(inst))) return `${instName} differs from the start of ${proofName}`;
    const c = COUNTS[proofName], view = Buffer.from(proof);
    for (let i = 0; i < 3; i++) if (view.readBigUInt64LE(c.at + 8 * i) !== c.values[i]) return `${proofName}: count ${i} is ${view.readBigUInt64LE(c.at + 8 * i)}, want ${c.values[i]}`;
    const problem = blindFormProblem(proof, BLIND[proofName], true);
    if (problem) return `${proofName}: ${problem}`;
  }
  return null;
}
