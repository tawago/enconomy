const src = require('./node_modules/circomlibjs/src/poseidon_constants.json'); const fs = require('fs');
const out = {};
for (const n of [1, 2, 3]) { const t = n + 1;
  out['t' + t] = { RF: 8, RP: [56, 57, 56][n - 1], C: src.C[t - 2], M: src.M[t - 2] }; }
fs.writeFileSync('poseidon_bn254_t2_t4.json', JSON.stringify(out)); for (const k in out) console.log(k, out[k].C.length, out[k].M.length, out[k].C[0]);
