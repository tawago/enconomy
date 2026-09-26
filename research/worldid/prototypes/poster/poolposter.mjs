// poolposter: permissionless poster. Holds only a gas key; the attestation carries the authority.
import { createPublicClient, createWalletClient, http, parseAbi, nonceManager, BaseError, ContractFunctionRevertedError } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { worldchain } from 'viem/chains'
const RPC = process.env.RPC, API = process.env.POP_API, SIDS = process.argv.slice(2)
const chain = { ...worldchain, rpcUrls: { default: { http: [RPC] } } }
const account = privateKeyToAccount(process.env.POSTER_PK)   // no nonceManager: one sender, one tx in flight
let lane = Promise.resolve()                                    // serial send queue = the only nonce owner
const serial = f => (lane = lane.then(f, f))
const pub = createPublicClient({ chain, transport: http(RPC), pollingInterval: 500 })
const wal = createWalletClient({ chain, transport: http(RPC), account })
const abi = parseAbi(['function posted(uint256) view returns (bool)',
  'function postPresence(uint256 leaf, bytes32 pairTag, uint64 expiry, bytes32 r, bytes32 s)',
  'error BadAttestation()', 'error Expired(uint64)', 'error LeafAlreadyPosted(uint256)'])
const sleep = ms => new Promise(r => setTimeout(r, ms))
async function one(sid) {
  const t0 = Date.now()
  for (;;) {                                        // poll the public endpoint every 500 ms
    let res; try { res = await fetch(`${API}/v1/session/${sid}/attestation`) } catch { await sleep(500); continue }  // server blip: retry
    if (res.status === 404) return `${sid}: unknown`
    const a = await res.json()
    if (a.state !== 'done') { await sleep(500); continue }
    if (a.verdict !== 'NEAR') return `${sid}: ${a.verdict}, nothing to post`
    const c = a.consumer
    if (c?.kind !== 'pool-xfer' || c.chain_id !== chain.id) return `${sid}: not for this pool`
    const leaf = BigInt(c.leaf)
    const args = [leaf, c.att.pair_tag, BigInt(c.att.expiry), c.att.r, c.att.s]
    return await serial(async () => {
     try {
      if (await pub.readContract({ address: c.address, abi, functionName: 'posted', args: [leaf] })) return `${sid}: leaf already posted, skip`
      const { request } = await pub.simulateContract({ account, address: c.address, abi, functionName: 'postPresence', args })
      const nonce = await pub.getTransactionCount({ address: account.address, blockTag: 'pending' })
      const hash = await wal.writeContract({ ...request, nonce })
      const rc = await pub.waitForTransactionReceipt({ hash, pollingInterval: 500, timeout: 60_000 })
      return `${sid}: ${rc.status} nonce ${nonce} block ${rc.blockNumber} gas ${rc.gasUsed} in ${Date.now() - t0} ms`
    } catch (e) {
      const r = e instanceof BaseError && e.walk(x => x instanceof ContractFunctionRevertedError)
      return `${sid}: revert ${r?.data?.errorName ?? e.shortMessage}`
    }
    })
  }
}
for (const line of await Promise.all(SIDS.map(one))) console.log(line)
