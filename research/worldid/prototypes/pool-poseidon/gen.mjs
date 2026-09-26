import { poseidon1, poseidon2, poseidon3 } from 'poseidon-lite';
import { buildPoseidon, buildPoseidonReference, buildPoseidonOpt } from 'circomlibjs';
import fs from 'fs';
const p = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const TAG_PAYER = 0x706f702d7061796572n, TAG_PRES = 0x706f702d70726573n, LABEL_TRANSFER = 0x706f702d7472616e73666572n;
// deterministic "random" 31-byte values
const r = (s) => BigInt('0x' + Buffer.from(s.padEnd(31, '.')).toString('hex').slice(0, 62));
const nul = r('existingNullifier'), sec = r('existingSecret'), qn = r('payeeNullifier'), qs = r('payeeSecret');
const value = 1000000000000000n, label = 0x1234567890abcdefn;
const cases = [
  { name: 'p1_zero', in: [0n] }, { name: 'p1_one', in: [1n] }, { name: 'p1_pm1', in: [p - 1n] },
  { name: 'p2_12', in: [1n, 2n] }, { name: 'p2_zero', in: [0n, 0n] }, { name: 'p2_pm1', in: [p - 1n, p - 1n] },
  { name: 'p3_123', in: [1n, 2n, 3n] }, { name: 'p3_zero', in: [0n, 0n, 0n] }, { name: 'p3_pm1', in: [p - 1n, p - 1n, p - 1n] },
  // non-canonical (>= p): expect == hash(x mod p) everywhere that accepts them
  { name: 'p2_noncanon', in: [p + 1n, 2n], note: 'input >= p' },
  { name: 'p2_max256', in: [(1n << 256n) - 1n, 0n], note: 'input = 2^256-1' },
];
// pool objects chain
const H = (xs) => [poseidon1, poseidon2, poseidon3][xs.length - 1](xs);
const pre = H([nul, sec]); const commitment = H([value, label, pre]); const nullifierHash = H([nul]);
const payerTag = H([TAG_PAYER, nul]); const payeePre = H([qn, qs]);
const payeeCommitment = H([value, LABEL_TRANSFER, payeePre]); const leaf = H([TAG_PRES, payerTag, payeeCommitment]);
cases.push(
  { name: 'pool_precommitment', in: [nul, sec] }, { name: 'pool_commitment', in: [value, label, pre] },
  { name: 'pool_nullifierHash', in: [nul] }, { name: 'pool_payerTag', in: [TAG_PAYER, nul] },
  { name: 'pool_payeePre', in: [qn, qs] }, { name: 'pool_payeeCommitment', in: [value, LABEL_TRANSFER, payeePre] },
  { name: 'pool_presenceLeaf', in: [TAG_PRES, payerTag, payeeCommitment] });
const cw = await buildPoseidon(); const cr = await buildPoseidonReference(); const co = await buildPoseidonOpt();
let ok = true;
for (const c of cases) {
  const lite = H(c.in);
  const a = cw.F.toObject(cw(c.in)), b = cr.F.toObject(cr(c.in)), d = co.F.toObject(co(c.in));
  c.out = '0x' + lite.toString(16).padStart(64, '0');
  const agree = lite === a && a === b && b === d; ok &&= agree;
  console.log(c.name.padEnd(22), agree ? 'AGREE' : `MISMATCH lite=${lite} wasm=${a} ref=${b} opt=${d}`);
}
const canon = cases.map(c => ({ name: c.name, t: c.in.length + 1, in: c.in.map(x => '0x' + x.toString(16).padStart(64, '0')), out: c.out, ...(c.note ? { note: c.note } : {}) }));
fs.writeFileSync('golden.json', JSON.stringify({ field: 'BN254 Fr', p: p.toString(), hash: 'circomlib Poseidon(n), t=n+1, x^5, RF=8, RP=[56,57,56]', cases: canon }, null, 1));
console.log(ok ? 'ALL AGREE' : 'FAIL');
