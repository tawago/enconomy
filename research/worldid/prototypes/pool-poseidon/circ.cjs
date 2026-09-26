const g = require('./golden.json'); const snarkjs = require('snarkjs'); const fs = require('fs');
(async () => {
  let ok = true;
  for (const c of g.cases) {
    const n = c.in.length; const dir = `h${n}_js`;
    try {
      const wtns = { type: 'mem' };
      await snarkjs.wtns.calculate({ in: c.in.map(x => BigInt(x).toString()) }, `${dir}/h${n}.wasm`, wtns);
      const w = await snarkjs.wtns.exportJson(wtns);
      const out = '0x' + BigInt(w[1]).toString(16).padStart(64, '0');
      const m = out === c.out; ok &&= m; console.log(c.name.padEnd(22), m ? 'AGREE' : 'MISMATCH ' + out);
    } catch (e) { console.log(c.name.padEnd(22), 'ERROR', String(e.message).slice(0, 120)); }
  }
  console.log(ok ? 'CIRCUIT ALL AGREE' : 'CIRCUIT FAIL'); process.exit(0);
})();
