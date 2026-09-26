import crypto from 'node:crypto';
import fs from 'node:fs';
const N = BigInt('0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551');
const HC = Buffer.from([16,70,218,155,213,251,245,7,204,185,139,218,5,74,20,209,142,74,215,186,20,251,131,21,79,193,58,45,113,25,147,22]);
const HS = '0x1234567890abcdef';
const HC_B = Buffer.from([1,55,111,74,97,36,86,37,115,126,130,5,73,44,145,69,243,173,162,127,143,251,218,28,50,81,226,248,200,85,28,178]);
const HS_B = '0xfeedbeef';
const kp = () => crypto.generateKeyPairSync('ec', { namedCurve: 'P-256' });
const raw = (k) => { const j = k.publicKey.export({ format: 'jwk' }); return Buffer.concat([Buffer.from(j.x, 'base64url'), Buffer.from(j.y, 'base64url')]); };
function sign(k, msg) {
  const sig = crypto.sign('sha256', msg, { key: k.privateKey, dsaEncoding: 'ieee-p1363' });
  let s = BigInt('0x' + sig.subarray(32).toString('hex'));
  if (s > N / 2n) s = N - s;
  return Buffer.concat([sig.subarray(0, 32), Buffer.from(s.toString(16).padStart(64, '0'), 'hex')]);
}
const issuer = kp(), A = kp(), B = kp();
const nonce = crypto.randomBytes(32);
function transcript(role, self, partner, half) {
  const t = Buffer.alloc(311);
  t.write('POPT', 0); t[4] = 2; t[5] = role.charCodeAt(0); t[6] = 0; nonce.copy(t, 7);
  t[39] = 4; raw(self).copy(t, 40); t[104] = 4; raw(partner).copy(t, 105);
  t.writeUInt32BE(48000, 169); t.writeInt32BE(half, 173);
  crypto.randomBytes(32).copy(t, 177); t.writeInt32BE(-12, 233); crypto.randomBytes(32).copy(t, 237);
  return t;
}
function cred(dev, hc) {
  const c = Buffer.alloc(111); c.write('SBcred3', 0); raw(dev).copy(c, 7);
  c.writeBigUInt64BE(2000000000n, 71); hc.copy(c, 79); return c;
}
const arr = (b) => '[' + [...b].join(', ') + ']';
const ix = raw(issuer).subarray(0, 32), iy = raw(issuer).subarray(32);
const h16=(b,o)=>'"0x'+b.subarray(o,o+16).toString('hex')+'"';
const pub = `issuer = [${h16(ix,0)}, ${h16(ix,16)}, ${h16(iy,0)}, ${h16(iy,16)}]\nnow = "1790000000"\nscope = "0x5afe"\ncontext = "0x0123456789abcdef"\n`;
const side = (role, self, partner, half, hc) => { const t = transcript(role, self, partner, half); const c = cred(self, hc);
  return { t: arr(t), s: arr(sign(self, t)), c: arr(c), cs: arr(sign(issuer, c)) }; };
const a = side('A', A, B, 5000, HC), b = side('B', B, A, 4916, HC_B);
fs.writeFileSync('half/Prover.toml', `transcript = ${a.t}\nsig_t = ${a.s}\ncred = ${a.c}\nsig_c = ${a.cs}\nholder_secret = "${HS}"\n` + pub);
fs.writeFileSync('half/ProverB.toml', `transcript = ${b.t}\nsig_t = ${b.s}\ncred = ${b.c}\nsig_c = ${b.cs}\nholder_secret = "${HS_B}"\n` + pub);
fs.writeFileSync('pair/Prover.toml', `t_a = ${a.t}\ns_a = ${a.s}\nc_a = ${a.c}\ncs_a = ${a.cs}\nhs_a = "${HS}"\n` +
  `t_b = ${b.t}\ns_b = ${b.s}\nc_b = ${b.c}\ncs_b = ${b.cs}\nhs_b = "${HS_B}"\n` + pub);
console.log('ok nonce', nonce.toString('hex'));
