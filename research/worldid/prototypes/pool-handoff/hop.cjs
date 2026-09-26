// laptop-wallet <-> phone PoP handoff prototype: popreq1 / popoff1 / popctx1 codecs, one QR hop (render PNG -> decode), phone check.
const NM='/private/tmp/claude-501/-Users-takahiro-ogawa-dev-enconomy/3d9dd236-bf59-4c81-91f5-6bb7c5ebc6e3/scratchpad/pool/privacy-pools-core/node_modules/';
const {poseidon2,poseidon3}=require(NM+'poseidon-lite');
const QR=require('qrcode'), jsQR=require('jsqr'), {PNG}=require('pngjs'), crypto=require('crypto'), fs=require('fs');
const P=21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const TAG_PAYER=0x706f702d7061796572n, TAG_PRES=0x706f702d70726573n, LABEL_TRANSFER=0x706f702d7472616e73666572n;
const CHAIN=480, POOL=Buffer.from('1111111111111111111111111111111111111111','hex');
const be=(x,n)=>{const b=Buffer.alloc(n);let v=BigInt(x);for(let i=n-1;i>=0;i--){b[i]=Number(v&255n);v>>=8n;}if(v)throw Error('overflow');return b;};
const rd=(b)=>BigInt('0x'+(b.toString('hex')||'0'));
const b64u=b=>b.toString('base64url'), unb64u=s=>Buffer.from(s,'base64url');
const sha=(...p)=>crypto.createHash('sha256').update(Buffer.concat(p)).digest();
const rand31=()=>rd(crypto.randomBytes(31));   // < 2^248 < p
// ---- codecs
function encReq({chainId,pool,value,payeePre,expiresAt,reqId}){ // 97 B
  return 'popreq1:'+b64u(Buffer.concat([Buffer.from('PRQ1'),Buffer.from([1]),be(chainId,4),pool,be(value,16),be(payeePre,32),be(expiresAt,4),reqId]));}
function decReq(s){const b=unb64u(s.slice(8));if(b.length!==97||b.subarray(0,4).toString()!=='PRQ1'||b[4]!==1)throw Error('bad_req');
  const payeePre=rd(b.subarray(29+16,77)); if(payeePre>=P)throw Error('bad_field');
  return {chainId:b.readUInt32BE(5),pool:b.subarray(9,29),value:rd(b.subarray(29,45)),payeePre,expiresAt:b.readUInt32BE(77),reqId:b.subarray(81,97)};}
function encOff({reqId,payerTag}){return 'popoff1:'+b64u(Buffer.concat([Buffer.from('POF1'),Buffer.from([1]),reqId,be(payerTag,32)]));} // 53 B
function decOff(s){const b=unb64u(s.slice(8));if(b.length!==53||b.subarray(0,4).toString()!=='POF1')throw Error('bad_off');return {reqId:b.subarray(5,21),payerTag:rd(b.subarray(21,53))};}
function encCtx({role,chainId,pool,leaf,value,expiresAt}){ // 82 B
  return 'popctx1:'+b64u(Buffer.concat([Buffer.from('PCX1'),Buffer.from([1,role]),be(chainId,4),pool,be(leaf,32),be(value,16),be(expiresAt,4)]));}
function decCtx(s){const b=unb64u(s.slice(8));if(b.length!==82||b.subarray(0,4).toString()!=='PCX1'||b[4]!==1)throw Error('bad_ctx');
  return {role:b[5],chainId:b.readUInt32BE(6),pool:b.subarray(10,30),leaf:rd(b.subarray(30,62)),value:rd(b.subarray(62,78)),expiresAt:b.readUInt32BE(78)};}
// ---- math
const payeeCommitment=(v,pre)=>poseidon3([v,LABEL_TRANSFER,pre]);
const leafOf=(tag,pc)=>poseidon3([TAG_PRES,tag,pc]);
const ctxOf=(chainId,pool,leaf)=>sha(Buffer.from('enconomy/pool-xfer/v1'),be(chainId,32),pool,be(leaf,32));
const nonceOf=(ctx,salt)=>sha(Buffer.from('enconomy/pop-nonce/v1'),ctx,salt);
(async()=>{
  const now=Math.floor(Date.now()/1000), value=1_200_000_000_000_000n; // 0.0012 ETH
  // 1. WQ (payee wallet, laptop): draw secrets, keep them, show popreq1
  const q={nul:rand31(),sec:rand31()}; q.pre=poseidon2([q.nul,q.sec]); const reqId=crypto.randomBytes(16);
  const req=encReq({chainId:CHAIN,pool:POOL,value,payeePre:q.pre,expiresAt:now+600,reqId});
  // 2. WP: parse req, pick note, payerTag, leaf, ctx; show popoff1
  const r=decReq(req); const pNul=rand31(); const payerTag=poseidon2([TAG_PAYER,pNul]);
  const leafP=leafOf(payerTag,payeeCommitment(r.value,r.payeePre)); const ctxP=ctxOf(r.chainId,r.pool,leafP);
  const off=encOff({reqId:r.reqId,payerTag});
  // 3. WQ: recompute with OWN value/payeePre
  const o=decOff(off); if(!o.reqId.equals(reqId))throw Error('reqId');
  const leafQ=leafOf(o.payerTag,payeeCommitment(value,q.pre)); const ctxQ=ctxOf(CHAIN,POOL,leafQ);
  console.log('ctx wallets agree:',ctxP.equals(ctxQ));
  const ctxStr=encCtx({role:1,chainId:CHAIN,pool:POOL,leaf:leafQ,value,expiresAt:now+600});
  // 4. ONE QR HOP: WQ screen -> PQ camera. Render PNG at 4 px/module, decode with jsQR.
  for(const [name,s] of [['popreq1',req],['popoff1',off],['popctx1',ctxStr]]){
    const q0=QR.create(s,{errorCorrectionLevel:'M'}); console.log(name,'chars',s.length,'QR version',q0.version,'modules',q0.modules.size);}
  await QR.toFile('popctx1.png',ctxStr,{errorCorrectionLevel:'M',scale:4,margin:2});
  const png=PNG.sync.read(fs.readFileSync('popctx1.png')); const dec=jsQR(new Uint8ClampedArray(png.data),png.width,png.height);
  console.log('png',png.width+'x'+png.height,'decoded equal:',dec&&dec.data===ctxStr);
  // 5. PQ phone: expected ctx from own wallet; server session view gives context+nonce_salt
  const exp=decCtx(dec.data); exp.ctx=ctxOf(exp.chainId,exp.pool,exp.leaf); const salt=crypto.randomBytes(32);
  const check=(view)=>{ if(exp.expiresAt<=now)return 'REFUSE expired';
    if(!Buffer.from(view.context,'hex').equals(exp.ctx))return 'REFUSE context_mismatch(ctx)';
    if(!nonceOf(Buffer.from(view.context,'hex'),Buffer.from(view.nonce_salt,'hex')).equals(Buffer.from(view.nonce,'hex')))return 'REFUSE context_mismatch(nonce)';
    return 'CONFIRM receive '+exp.value+' wei'; };
  const honest={context:ctxP.toString('hex'),nonce_salt:salt.toString('hex'),nonce:nonceOf(ctxP,salt).toString('hex')};
  console.log('honest session:',check(honest));
  const preR=poseidon2([rand31(),rand31()]); const ctxR=ctxOf(CHAIN,POOL,leafOf(payerTag,payeeCommitment(value,preR)));
  console.log('server binds leaf paying sybil R:',check({context:ctxR.toString('hex'),nonce_salt:salt.toString('hex'),nonce:nonceOf(ctxR,salt).toString('hex')}));
  console.log('right ctx, random nonce:',check({...honest,nonce:crypto.randomBytes(32).toString('hex')}));
  const ctxV=ctxOf(CHAIN,POOL,leafOf(payerTag,payeeCommitment(value-1n,q.pre)));
  console.log('payer changes value:',check({context:ctxV.toString('hex'),nonce_salt:salt.toString('hex'),nonce:nonceOf(ctxV,salt).toString('hex')}));
  // test vector (fixed inputs)
  const tv={payerTag:5n,value:1200n,payeePre:7n}; const tl=leafOf(tv.payerTag,payeeCommitment(tv.value,tv.payeePre));
  const tc=ctxOf(480,POOL,tl); console.log('TV leaf',tl.toString(),'\nTV ctx',tc.toString('hex'),'\nTV nonce(salt=00*32)',nonceOf(tc,Buffer.alloc(32)).toString('hex'));
  console.log('TV popctx1',encCtx({role:1,chainId:480,pool:POOL,leaf:tl,value:1200n,expiresAt:1790000000}));
})();
