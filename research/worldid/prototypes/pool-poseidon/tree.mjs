import { LeanIMT } from '@zk-kit/lean-imt'; import { poseidon2 } from 'poseidon-lite'; import fs from 'fs';
const g = JSON.parse(fs.readFileSync('golden.json'));
const leaves = g.cases.filter(c => c.name.startsWith('pool_')).map(c => BigInt(c.out)); // 7 leaves
const t = new LeanIMT((a, b) => poseidon2([a, b]));
g.leanimt = { hash: 'poseidon2 / PoseidonT3', leaves: leaves.map(x => '0x' + x.toString(16).padStart(64, '0')), rootsAfterEachInsert: [], depths: [] };
for (const l of leaves) { t.insert(l); g.leanimt.rootsAfterEachInsert.push('0x' + t.root.toString(16).padStart(64, '0')); g.leanimt.depths.push(t.depth); }
fs.writeFileSync('golden.json', JSON.stringify(g, null, 1)); console.log(g.leanimt.depths, g.leanimt.rootsAfterEachInsert.at(-1));
