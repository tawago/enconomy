// payee-cannot-verify-leaf: payee-side leaf/ctx recompute + circuit SAT/UNSAT
const {LeanIMT} = require('@zk-kit/lean-imt');
const {poseidon1,poseidon2,poseidon3} = require('poseidon-lite');
const {keccak256, encodeAbiParameters, toHex} = require('viem');
const snarkjs = require('snarkjs');
const h=(a,b)=>poseidon2([a,b]);
const pad=(s,n)=>{const a=s.map(String);while(a.length<n)a.push('0');return a;};
const TAG_PAYER=0x706f702d7061796572n, TAG_PRES=0x706f702d70726573n, LABEL_TRANSFER=0x706f702d7472616e73666572n;
const POOL='0x1111111111111111111111111111111111111111', CHAIN=480n;
const SID='0x0123456789abcdef0123456789abcdef', NB=1790000000n;

// payee-side pure functions (what the app would run)
const payeeCommitment=(value,pre)=>poseidon3([value,LABEL_TRANSFER,pre]);
const leafOf=(payerTag,pc)=>poseidon3([TAG_PRES,payerTag,pc]);
const ctxOf=(leaf)=>keccak256(encodeAbiParameters([{type:'string'},{type:'address'},{type:'uint256'}],['pool-xfer-v1',POOL,leaf]));
const nonceOf=(ctx)=>keccak256(encodeAbiParameters(
  [{type:'bytes32'},{type:'uint256'},{type:'address'},{type:'bytes32'},{type:'uint64'},{type:'bytes16'}],
  [keccak256(toHex('pop-ctx-v1')),CHAIN,POOL,ctx,NB,SID]));
function payeeCheck({payerTag, value, payeePre, ctxFromServer, nonceFromServer}){
  const leaf=leafOf(payerTag,payeeCommitment(value,payeePre));
  const ctx=ctxOf(leaf);
  if(ctx!==ctxFromServer) return 'REFUSE context_mismatch(ctx)';
  if(nonceOf(ctx)!==nonceFromServer) return 'REFUSE context_mismatch(nonce)';
  return 'CONFIRM';
}

// payer P note
const label=11n, value=5000n, nul=777n, sec=888n, newNul=999n, newSec=1001n, tv=1200n;
const inCommit=poseidon3([value,label,poseidon2([nul,sec])]);
const payerTag=poseidon2([TAG_PAYER,nul]);
const nullifierHash=poseidon1([nul]);
// real payee Q, sybil R
const preQ=poseidon2([31337n,4242n]), preR=poseidon2([666n,667n]);
const pcQ=payeeCommitment(tv,preQ), pcR=payeeCommitment(tv,preR);
const leafQ=leafOf(payerTag,pcQ), leafR=leafOf(payerTag,pcR);

const st=new LeanIMT(h); [1n,2n,inCommit,3n].forEach(x=>st.insert(x));
const sp=st.generateProof(st.indexOf(inCommit));
function input(presLeaves, leaf, payeePre, nullifierOverride){
  const pt=new LeanIMT(h); presLeaves.forEach(x=>pt.insert(x));
  const i=pt.indexOf(leaf); const pp=pt.generateProof(i<0?0:i);
  return {stateRoot:String(st.root), stateTreeDepth:String(st.depth), presenceRoot:String(pt.root), presenceTreeDepth:String(pt.depth), context:'42',
   label:String(label), existingValue:String(value), existingNullifier:String(nullifierOverride??nul), existingSecret:String(sec), newNullifier:String(newNul), newSecret:String(newSec),
   transferValue:String(tv), payeePrecommitment:String(payeePre), stateSiblings:pad(sp.siblings,32), stateIndex:String(sp.index), presenceSiblings:pad(pp.siblings,20), presenceIndex:String(pp.index)};
}
async function sat(inp){
  try{ await snarkjs.wtns.calculate(inp,'outT/presenceTransfer_js/presenceTransfer.wasm',{type:'mem'}); return 'SAT'; }
  catch(e){ return 'UNSAT ('+String(e.message).split('\n')[0].slice(0,70)+')'; }
}
(async()=>{
  const ctxR=ctxOf(leafR), ctxQ=ctxOf(leafQ);
  console.log('1 attack: server ctx built from leafR, Q checks own pcQ  ->', payeeCheck({payerTag,value:tv,payeePre:preQ,ctxFromServer:ctxR,nonceFromServer:nonceOf(ctxR)}));
  console.log('2 honest: server ctx from leafQ                          ->', payeeCheck({payerTag,value:tv,payeePre:preQ,ctxFromServer:ctxQ,nonceFromServer:nonceOf(ctxQ)}));
  console.log('3 value tamper: ctx from leaf with value 1100 vs Q expects 1200 ->', payeeCheck({payerTag,value:tv,payeePre:preQ,ctxFromServer:ctxOf(leafOf(payerTag,payeeCommitment(1100n,preQ))),nonceFromServer:nonceOf(ctxOf(leafOf(payerTag,payeeCommitment(1100n,preQ))))}));
  console.log('4 ctx ok but nonce swapped (other ctx) ->', payeeCheck({payerTag,value:tv,payeePre:preQ,ctxFromServer:ctxQ,nonceFromServer:nonceOf(ctxR)}));
  console.log('5 circuit: tree has leafQ, P pays Q  ->', await sat(input([5n,leafQ,6n],leafQ,preQ)));
  console.log('6 circuit: tree has leafQ, P pays R  ->', await sat(input([5n,leafQ,6n],leafQ,preR)));
  console.log('7 circuit: tree has leafR (opaque-sign attack), P pays R ->', await sat(input([5n,leafR,6n],leafR,preR)));
  const fakeTag=poseidon2([TAG_PAYER,123456n]); const leafFake=leafOf(fakeTag,pcQ);
  console.log('8 fake payerTag: Q check ->', payeeCheck({payerTag:fakeTag,value:tv,payeePre:preQ,ctxFromServer:ctxOf(leafFake),nonceFromServer:nonceOf(ctxOf(leafFake))}),
              '; circuit P spends real note vs leafFake ->', await sat(input([5n,leafFake,6n],leafFake,preQ)));
  console.log('9 payerTag != nullifierHash:', payerTag!==nullifierHash, '\n  payerTag     ', payerTag, '\n  nullifierHash', nullifierHash);
})();
