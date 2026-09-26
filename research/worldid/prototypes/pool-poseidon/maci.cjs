const { poseidon } = require('maci-crypto/build/ts/hashing.js'); const g = require('./golden.json');
let ok = true; for (const c of g.cases) { let o; try { o = '0x' + poseidon(c.in.map(BigInt)).toString(16).padStart(64, '0'); } catch (e) { o = 'ERR ' + e.message; }
  const m = o === c.out; ok &&= m; if (!m) console.log(c.name, 'MISMATCH', o.slice(0, 80)); }
console.log(ok ? 'MACI ALL AGREE' : 'MACI has mismatches', require('fs').readFileSync('node_modules/@zk-kit/poseidon-cipher/package.json','utf8').match(/"version": "([^"]+)/)[1]);
