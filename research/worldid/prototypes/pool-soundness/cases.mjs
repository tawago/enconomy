import { createRequire } from "module";
const require = createRequire("/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/ppe2e/js/");
const { LeanIMT } = require("@zk-kit/lean-imt");
const { poseidon2, poseidon3 } = require("poseidon-lite");
const snarkjs = require("snarkjs");
const K = "/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/ppe2e/keys/";
const P = 21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const h=(a,b)=>poseidon2([a,b]); const pad=(s,n)=>{const a=s.map(String);while(a.length<n)a.push('0');return a;};
const TAG_PAYER=0x706f702d7061796572n, TAG_PRES=0x706f702d70726573n, LT=0x706f702d7472616e73666572n;
function mk(o={}) {
  const label=11n, value=o.value??5000n, nul=777n, sec=888n, newNul=o.newNul??999n, newSec=1001n, tv=o.tv??1200n;
  const payeePre=h(31337n,4242n);
  const inCommit=poseidon3([value,label,h(nul,sec)]);
  const st=new LeanIMT(h); [1n,2n,inCommit,3n].forEach(x=>st.insert(x)); const sp=st.generateProof(st.indexOf(inCommit));
  const pc=poseidon3([tv,LT,payeePre]); const leaf=poseidon3([TAG_PRES,h(TAG_PAYER,nul),pc]);
  const pt=new LeanIMT(h); [5n,leaf,6n].forEach(x=>pt.insert(x)); const pp=pt.generateProof(pt.indexOf(leaf));
  const inp={stateRoot:st.root,stateTreeDepth:st.depth,presenceRoot:pt.root,presenceTreeDepth:pt.depth,context:42n,label,existingValue:value,
   existingNullifier:nul,existingSecret:sec,newNullifier:newNul,newSecret:newSec,transferValue:tv,payeePrecommitment:payeePre,
   stateSiblings:pad(sp.siblings,32),stateIndex:sp.index,presenceSiblings:pad(pp.siblings,20),presenceIndex:pp.index, ...(o.over||{})};
  return JSON.parse(JSON.stringify(inp,(_,v)=>typeof v==='bigint'?v.toString():v));
}
const r1cs = K+"presenceTransfer.r1cs";
const cases = {
  good: mk(), zeroValue: mk({tv:0n}), fullSpend_change0: mk({tv:5000n}),
  sameNullifier: mk({newNul:777n}),
  stateDepth0_real2: mk({over:{stateTreeDepth:0}}), stateDepth32: mk({over:{stateTreeDepth:32}}), stateDepth33: mk({over:{stateTreeDepth:33}}),
  stateDepth_pm1: mk({over:{stateTreeDepth:P-1n}}), stateDepth_pm31: mk({over:{stateTreeDepth:P-31n}}), stateDepth_pm32: mk({over:{stateTreeDepth:P-32n}}),
  presDepth20: mk({over:{presenceTreeDepth:20}}), presDepth21: mk({over:{presenceTreeDepth:21}}),
  presDepth_pm1: mk({over:{presenceTreeDepth:P-1n}}), presDepth_pm43: mk({over:{presenceTreeDepth:P-43n}}), presDepth_pm44: mk({over:{presenceTreeDepth:P-44n}}),
  tv_2pow128: mk({tv:1n<<128n, value:(1n<<128n)+5n}),
  tv_negwrap: mk({over:{transferValue:(P-1n).toString()}}),
};
for (const [n,inp] of Object.entries(cases)) {
  let res;
  try {
    const w={type:"mem"}; await snarkjs.wtns.calculate(inp, K+"presenceTransfer.wasm", w);
    const ok = await snarkjs.wtns.check(r1cs, w, {info(){},warn(){},error(){},debug(){}});
    res = ok ? "SAT" : "UNSAT(r1cs check)";
    if (ok) { const {wtns}=w; }
  } catch(e) { res = "UNSAT (" + String(e.message).split("\n")[0].slice(0,90) + ")"; }
  console.log(n.padEnd(20), res);
}
process.exit(0);
