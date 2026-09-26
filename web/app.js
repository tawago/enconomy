// Met on ENS: static page, reads Sepolia ENSv2 directly. No backend.
import { createPublicClient, http, fallback, parseAbi, namehash, labelhash } from 'https://cdn.jsdelivr.net/npm/viem@2.56.8/+esm'
import { sepolia } from 'https://cdn.jsdelivr.net/npm/viem@2.56.8/chains/+esm'
import { normalize } from 'https://cdn.jsdelivr.net/npm/viem@2.56.8/ens/+esm'

// ---------- constants
const ZERO = '0x0000000000000000000000000000000000000000'
const CHUNK = 45000n
const FEED_MAX = 8
const DEFAULT_RPCS = [
  'https://ethereum-sepolia-rpc.publicnode.com',
  'https://sepolia.gateway.tenderly.co',
  'https://1rpc.io/sepolia',
]
const KEYS = { met: 'eth.enconomy.met', meetings: 'eth.enconomy.meetings', zk: 'eth.enconomy.zk' }
const ETHERSCAN = 'https://sepolia.etherscan.io'
const EXPLORER = 'https://explorer.ens.dev'
const ENSAPP = 'https://app.ens.dev'

// Hand-written from the MeetResolver interface (design doc §5.1).
const MEET_ABI = parseAbi([
  'event TextChanged(bytes32 indexed node, string indexed indexedKey, string key, string value)',
  'event Member(bytes32 indexed node, bytes32 indexed labelhash, string label)',
  'event Met(bytes32 indexed meetingId, bytes32 indexed nodeLo, bytes32 indexed nodeHi, bytes32 pairKey, uint32 timeBucket, bytes32 evidence, bool firstTime)',
  'event ZkVerified(bytes32 indexed meetingId)',
  'event MeetVoided(bytes32 indexed meetingId)',
  'function countsOf(bytes32 labelhash) view returns (bool registered, uint32 met, uint32 meetings, uint32 zk)',
  'function DEPLOY_BLOCK() view returns (uint256)',
  'function meetingOf(bytes32 meetingId) view returns (uint256 resLo, uint256 resHi, bool exists, bool zk, bool void)',
  'function REG() view returns (address)',
  'function eventName() view returns (string)',
])
const SCAN_EVENTS = MEET_ABI.filter((x) => x.type === 'event' && ['Member', 'Met', 'ZkVerified', 'MeetVoided'].includes(x.name))
const REG_ABI = parseAbi([
  'struct State { uint8 status; uint64 expiry; address latestOwner; uint256 tokenId; uint256 resource; }',
  'function getState(uint256 anyId) view returns (State)',
  'function getSubregistry(string label) view returns (address)',
  'function getResolver(string label) view returns (address)',
])
const UR_ABI = parseAbi(['function ROOT_REGISTRY() view returns (address)'])
const STATUS = ['available', 'reserved', 'registered']

// ---------- helpers
const $ = (id) => document.getElementById(id)
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const short = (h, a = 6, b = 4) => (h && h.length > a + b + 2 ? `${h.slice(0, a)}…${h.slice(-b)}` : h || '')
const errMsg = (e) => (e && (e.shortMessage || e.message)) || String(e)
const errDetail = (e) => {
  const parts = []
  let x = e
  for (let i = 0; x && i < 4; i++) { if (x.details) parts.push(x.details); if (x.metaMessages) parts.push(x.metaMessages.join(' ')); x = x.cause }
  return (parts.join(' | ') || (e && e.message) || '').slice(0, 600)
}
const fmtInt = (n) => Number(n).toLocaleString('en-US')
const qs = new URLSearchParams(location.search)
const hourFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const hourOnly = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const hourDay = new Intl.DateTimeFormat(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const dateFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
function hourLabel(tb, fmt = hourFmt) {
  const a = new Date(Number(tb) * 3600000)
  const b = new Date((Number(tb) + 1) * 3600000)
  return `${fmt.format(a)}–${hourOnly.format(b)}`
}
// Compact hour for lists, full date in the tooltip.
const hourHtml = (tb) => `<span class="when" title="${esc(hourLabel(tb))}">${esc(hourLabel(tb, hourDay))}</span>`
const txLink = (tx, cls = 'tx') => `<a class="${cls}" href="${ETHERSCAN}/tx/${tx}" target="_blank" rel="noopener" title="${esc(tx)}">tx ${esc(short(tx, 6, 4))} ↗</a>`
const meetMarks = (m) => [
  m.firstTime ? '<span class="mark first">first meeting</span>' : '<span class="mark">met again</span>',
  m.zk ? '<span class="pill zk">ZK verified</span>' : '',
  m.void ? '<span class="pill void">voided</span>' : '',
].join('')
function ago(sec) {
  if (sec < 5) return 'just now'
  if (sec < 90) return `${Math.round(sec)} s ago`
  if (sec < 5400) return `${Math.round(sec / 60)} min ago`
  if (sec < 172800) return `${Math.round(sec / 3600)} h ago`
  return `${Math.round(sec / 86400)} d ago`
}
function keepParams(extra) {
  const p = new URLSearchParams()
  for (const k of ['parent', 'rpc', 'resolver']) if (qs.get(k)) p.set(k, qs.get(k))
  for (const [k, v] of Object.entries(extra || {})) if (v) p.set(k, v)
  const s = p.toString()
  return s ? `?${s}` : location.pathname
}

// ---------- state
const S = {
  cfg: null, parent: '', parentNode: null, resolver: null, resolverVia: '', reg: null, deployBlock: null,
  scannedTo: null, head: null, headAt: 0, rpcLabel: '',
  members: new Map(),   // node -> {node, labelhash, label, name}
  meets: new Map(),     // meetingId -> {id, nodeLo, nodeHi, firstTime, timeBucket, evidence, tx, block, logIndex, zk, void}
  seen: new Set(), pendingZk: new Set(), pendingVoid: new Set(),
  counts: new Map(),    // node -> {registered, met:{}, meetings:{}, zk:{}}
  profile: null,
  errors: new Map(),
  latestId: null, latestTs: null, booted: false, lastFull: 0,
}
let client

// ---------- errors (kept apart from empty values)
function setErr(key, title, e) { S.errors.set(key, { title, msg: e ? errMsg(e) : '', detail: e ? errDetail(e) : '' }); renderErrors() }
function clearErr(key) { if (S.errors.delete(key)) renderErrors() }
function renderErrors() {
  const box = $('errors')
  box.hidden = S.errors.size === 0
  box.innerHTML = [...S.errors.values()].map((x) =>
    `<div class="err-item"><b>${esc(x.title)}</b>${x.msg ? ` · ${esc(x.msg)}` : ''}${x.detail && x.detail !== x.msg ? `<details><summary>details</summary>${esc(x.detail)}</details>` : ''}</div>`).join('')
}

// ---------- chain reads
const ensText = (name, key) => client.getEnsText({ name, key, strict: true })
const readMeet = (functionName, args = []) => client.readContract({ address: S.resolver, abi: MEET_ABI, functionName, args })

async function discover() {
  if (qs.get('resolver')) { S.resolverVia = 'override (?resolver=)'; return qs.get('resolver') }
  const tryResolver = async (addr) => {
    if (!addr || addr.toLowerCase() === ZERO) return null
    try { await client.readContract({ address: addr, abi: MEET_ABI, functionName: 'DEPLOY_BLOCK' }); return addr } catch { return null }
  }
  let firstErr = null
  try {
    const r = await tryResolver(await client.getEnsResolver({ name: S.parent }))
    if (r) { S.resolverVia = 'ENS getEnsResolver'; return r }
  } catch (e) { firstErr = e }
  // Fallback: RootRegistry -> ETHRegistry.getResolver(label)
  try {
    const labels = S.parent.split('.')
    if (labels.length !== 2 || labels[1] !== 'eth') throw new Error('registry fallback only handles <label>.eth parents')
    let root = S.cfg.rootRegistry
    try { root = await client.readContract({ address: sepolia.contracts.ensUniversalResolver.address, abi: UR_ABI, functionName: 'ROOT_REGISTRY' }) } catch {}
    const eth = await client.readContract({ address: root, abi: REG_ABI, functionName: 'getSubregistry', args: ['eth'] })
    const r = await tryResolver(await client.readContract({ address: eth, abi: REG_ABI, functionName: 'getResolver', args: [labels[0]] }))
    if (r) { S.resolverVia = 'registry fallback'; return r }
  } catch (e) { firstErr = firstErr || e }
  if (firstErr) throw firstErr
  return null
}

async function checkRoot() {
  try {
    const live = await client.readContract({ address: sepolia.contracts.ensUniversalResolver.address, abi: UR_ABI, functionName: 'ROOT_REGISTRY' })
    clearErr('root')
    if (S.cfg.rootRegistry && live.toLowerCase() !== S.cfg.rootRegistry.toLowerCase()) {
      const b = $('banner')
      b.hidden = false
      b.innerHTML = `ENS Sepolia looks redeployed: the Universal Resolver now points at root registry <code>${esc(short(live, 8, 6))}</code>, this page was built for <code>${esc(short(S.cfg.rootRegistry, 8, 6))}</code>. Live names may be gone; see the verified snapshot below.`
    }
  } catch (e) { setErr('root', 'Could not read UR.ROOT_REGISTRY()', e) }
}

function ingest(logs) {
  const touched = new Set()
  const newMets = []
  let newMembers = false
  for (const l of logs) {
    const k = `${l.transactionHash}:${l.logIndex}`
    if (S.seen.has(k) || !l.eventName) continue
    S.seen.add(k)
    const a = l.args
    if (l.eventName === 'Member') {
      if (!S.members.has(a.node)) {
        S.members.set(a.node, { node: a.node, labelhash: a.labelhash, label: a.label, name: `${a.label}.${S.parent}` })
        newMembers = true
      }
      touched.add(a.node)
    } else if (l.eventName === 'Met') {
      const m = { id: a.meetingId, nodeLo: a.nodeLo, nodeHi: a.nodeHi, firstTime: a.firstTime, timeBucket: a.timeBucket, evidence: a.evidence,
        tx: l.transactionHash, block: l.blockNumber, logIndex: l.logIndex, zk: S.pendingZk.has(a.meetingId), void: S.pendingVoid.has(a.meetingId) }
      S.meets.set(a.meetingId, m)
      newMets.push(m)
      touched.add(a.nodeLo); touched.add(a.nodeHi)
    } else if (l.eventName === 'ZkVerified' || l.eventName === 'MeetVoided') {
      const field = l.eventName === 'ZkVerified' ? 'zk' : 'void'
      const m = S.meets.get(a.meetingId)
      if (m) { m[field] = true; touched.add(m.nodeLo); touched.add(m.nodeHi) }
      else (field === 'zk' ? S.pendingZk : S.pendingVoid).add(a.meetingId)
    }
  }
  return { touched, newMets, newMembers }
}

async function scan(from, to, note) {
  const all = { touched: new Set(), newMets: [], newMembers: false }
  for (let a = from; a <= to; a += CHUNK) {
    const b = a + CHUNK - 1n < to ? a + CHUNK - 1n : to
    if (note) $('boardNote').textContent = `reading logs ${fmtInt(a)}…${fmtInt(b)}`
    const logs = await client.getLogs({ address: S.resolver, events: SCAN_EVENTS, fromBlock: a, toBlock: b })
    const r = ingest(logs)
    r.touched.forEach((n) => all.touched.add(n))
    all.newMets.push(...r.newMets)
    all.newMembers = all.newMembers || r.newMembers
  }
  return all
}

function pickCount(t, chain, key) {
  if (t.status === 'fulfilled') {
    const s = t.value
    if (s === null || s === '') return { empty: true }
    const n = Number(s)
    if (!Number.isInteger(n)) return { err: `non-numeric text "${s}"` }
    const c = chain ? Number(chain[key]) : undefined
    return { v: n, mismatch: chain && c !== n ? c : undefined }
  }
  if (chain) return { v: Number(chain[key]), err: `ENS read failed, showing countsOf: ${errMsg(t.reason)}` }
  return { err: errMsg(t.reason) }
}

async function readCounts(m) {
  const [c, a, b, z] = await Promise.allSettled([
    readMeet('countsOf', [m.labelhash]),
    ensText(m.name, KEYS.met), ensText(m.name, KEYS.meetings), ensText(m.name, KEYS.zk),
  ])
  const chain = c.status === 'fulfilled' ? { registered: c.value[0], met: c.value[1], meetings: c.value[2], zk: c.value[3] } : null
  return {
    registered: chain ? chain.registered : undefined,
    chainErr: chain ? null : errMsg(c.reason),
    met: pickCount(a, chain, 'met'), meetings: pickCount(b, chain, 'meetings'), zk: pickCount(z, chain, 'zk'),
  }
}

async function refreshCounts(nodes) {
  const list = [...nodes].map((n) => S.members.get(n)).filter(Boolean)
  const res = await Promise.all(list.map(readCounts))
  list.forEach((m, i) => S.counts.set(m.node, res[i]))
}

// ---------- rendering: numbers
function cellHtml(st) {
  if (!st) return '<span class="none loading">…</span>'
  let h
  if (st.v != null) h = `<span class="num">${st.v}</span>`
  else if (st.empty) h = '<span class="none" title="empty text record">—</span>'
  else h = `<span class="err" title="${esc(st.err || 'error')}">error</span>`
  if (st.v != null && st.err) h += ` <span class="err" title="${esc(st.err)}">⚠</span>`
  if (st.mismatch !== undefined) h += `<span class="mismatch" title="countsOf() disagrees with the ENS text record">chain ${st.mismatch}</span>`
  return h
}
// Returns true when the value went up and an animation ran.
// Going up: the old digit rolls out, the new one rolls in, a "+n" pill floats beside it,
// then the number stays accent-coloured for a moment and fades back.
function setCell(el, st, animate) {
  const html = cellHtml(st)
  if (el.dataset.k === html) return false
  const prev = el.dataset.v !== undefined ? Number(el.dataset.v) : null
  el.dataset.k = html
  if (st && st.v != null) el.dataset.v = st.v; else delete el.dataset.v
  const up = animate && prev != null && st && st.v != null && st.v > prev
  if (!up) { el.innerHTML = html; return false }
  // Every step is driven by animationend (no timers), so pausing the page's animations freezes the whole moment.
  el.innerHTML = html.replace(/<span class="num">[^<]*<\/span>/, `<span class="num roll"><span class="out">${prev}</span><span class="in">${st.v}</span></span>`)
  const roll = el.querySelector('.num.roll')
  roll.querySelector('.in').addEventListener('animationend', () => {
    const n = document.createElement('span')
    n.className = 'num hot'
    n.textContent = st.v
    n.addEventListener('animationend', () => n.classList.remove('hot'), { once: true })
    roll.replaceWith(n)
  }, { once: true })
  const p = document.createElement('span')
  p.className = 'plus'
  p.textContent = `+${st.v - prev}`
  p.addEventListener('animationend', () => p.remove(), { once: true })
  el.appendChild(p)
  return true
}
// Restart a one-shot CSS animation class, and drop it when done so re-inserting the node cannot replay it.
function flash(el, cls) {
  el.classList.remove(cls)
  void el.offsetWidth
  el.classList.add(cls)
  const done = (e) => { if (e.target !== el) return; el.classList.remove(cls); el.removeEventListener('animationend', done) }
  el.addEventListener('animationend', done)
}
const nameHtml = (label) => `${esc(label)}<span class="dim">.${esc(S.parent)}</span>`
const labelOf = (node) => S.members.get(node)?.label
function nodeLink(node) {
  const m = S.members.get(node)
  if (!m) return `<span class="mono" title="${esc(node)}">${esc(short(node))}</span>`
  return `<a href="${esc(keepParams({ name: m.name }))}" data-name="${esc(m.name)}">${esc(m.label)}</a>`
}

// ---------- leaderboard
const rowEls = new Map()
function renderBoard(animate) {
  const ol = $('rows')
  const before = new Map()
  for (const [n, el] of rowEls) if (el.isConnected) before.set(n, el.getBoundingClientRect().top)
  const val = (st) => (st && st.v != null ? st.v : -1)
  const all = [...S.members.values()].map((m) => ({ m, c: S.counts.get(m.node) }))
  const shown = all.filter((x) => !x.c || x.c.registered !== false)
  const hidden = all.length - shown.length
  shown.sort((x, y) => val(y.c?.met) - val(x.c?.met) || val(y.c?.meetings) - val(x.c?.meetings) || x.m.label.localeCompare(y.m.label))
  const keep = new Set(shown.map((x) => x.m.node))
  for (const [n, el] of rowEls) if (!keep.has(n)) el.remove()
  shown.forEach(({ m, c }, i) => {
    let li = rowEls.get(m.node)
    if (!li) {
      li = document.createElement('li')
      li.className = 'row'
      li.innerHTML = `<span class="rk"></span><span class="nm">${nameHtml(m.label)}</span><span class="v met"></span><span class="v mt"></span><span class="v zk"></span>`
      li.addEventListener('click', () => go(m.name))
      rowEls.set(m.node, li)
    }
    li.querySelector('.rk').textContent = i + 1
    li.classList.toggle('sel', S.profile?.node === m.node)
    const up1 = setCell(li.querySelector('.met'), c?.met, animate)
    const up2 = setCell(li.querySelector('.mt'), c?.meetings, animate)
    setCell(li.querySelector('.zk'), c?.zk, animate)
    if (up1 || up2) flash(li, 'flash')
    if (ol.children[i] !== li) ol.insertBefore(li, ol.children[i] || null)
  })
  // FLIP: slide rows that changed rank
  if (animate) for (const [n, top] of before) {
    const el = rowEls.get(n)
    if (!el || !el.isConnected) continue
    const d = top - el.getBoundingClientRect().top
    if (Math.abs(d) > 2) el.animate([{ transform: `translateY(${d}px)` }, { transform: 'none' }], { duration: 700, easing: 'cubic-bezier(.2,.8,.2,1)' })
  }
  const empty = $('boardEmpty')
  empty.hidden = shown.length > 0
  if (!S.resolver) empty.textContent = `No MeetResolver found for ${S.parent} yet.`
  else if (S.scannedTo == null) empty.textContent = 'Reading the chain…'
  else empty.textContent = 'No names yet. The first claimed name shows up here within a block.'
  if (S.scannedTo != null) {
    $('boardNote').textContent = `live from ENS text records${hidden ? ` · ${hidden} revoked hidden` : ''}`
  }
  renderTotals(animate, shown.length)
}

// Hero totals: meetings = live (not voided) Met logs, names = names on the board.
function renderTotals(animate, names) {
  if (S.scannedTo == null) return
  const meets = [...S.meets.values()].filter((m) => !m.void).length
  setCell($('totMeet'), { v: meets }, animate)
  if (names != null) setCell($('totNames'), { v: names }, animate)
}

// ---------- meetings feed + latest card
function meetItem(m, cls = '', pair) {
  return `<li class="fi ${m.void ? 'void' : ''} ${cls}">
    <span class="pair">${pair || `${nodeLink(m.nodeLo)}<span class="x">⇄</span>${nodeLink(m.nodeHi)}`}</span>
    ${hourHtml(m.timeBucket)}
    <span class="sub">${meetMarks(m)}${txLink(m.tx)}</span>
  </li>`
}
const sortedMeets = () => [...S.meets.values()].sort((a, b) => (b.block > a.block ? 1 : b.block < a.block ? -1 : b.logIndex - a.logIndex))

let feedIds = new Set()
function renderFeed(animate) {
  const all = sortedMeets()
  const list = all.slice(0, FEED_MAX)
  $('feedWrap').hidden = !!S.profile || list.length === 0
  $('feedNote').textContent = all.length > list.length ? `latest ${list.length} of ${all.length}` : 'newest first'
  $('feed').innerHTML = list.map((m) => meetItem(m, animate && S.booted && !feedIds.has(m.id) ? 'newrow' : '')).join('')
  feedIds = new Set(list.map((m) => m.id))
}

async function renderLatest(animate) {
  const m = sortedMeets().find((x) => !x.void)
  const box = $('justMet')
  if (!m) { box.hidden = true; return }
  box.hidden = false
  const chip = (el, node) => {
    const mem = S.members.get(node)
    el.innerHTML = mem ? nameHtml(mem.label) : esc(short(node))
    el.href = mem ? keepParams({ name: mem.name }) : '#'
    el.dataset.name = mem ? mem.name : ''
  }
  chip($('justA'), m.nodeLo)
  chip($('justB'), m.nodeHi)
  const effect = m.firstTime ? 'both names: met +1, meetings +1' : 'meetings +1, met unchanged'
  $('justFoot').innerHTML = `${meetMarks(m)}<span class="effect">${effect}</span><span>${esc(hourLabel(m.timeBucket))}</span>${txLink(m.tx, 'mono')}`
  if (S.latestId !== m.id) {
    const fresh = animate && S.latestId !== null
    S.latestId = m.id
    S.latestTs = null
    if (fresh) { box.classList.remove('fresh'); void box.offsetWidth; box.classList.add('fresh'); setTimeout(() => box.classList.remove('fresh'), 5000) }
    try { const blk = await client.getBlock({ blockNumber: m.block }); if (S.latestId === m.id) S.latestTs = Number(blk.timestamp) } catch {}
    tickClock()
  }
}

// ---------- profile
function parseName(input) {
  let s = String(input || '').trim().toLowerCase().replace(/^https?:\/\/\S*[?&]name=/, '')
  if (!s) return null
  if (!s.includes('.')) s = `${s}.${S.parent}`
  const name = normalize(s)
  const label = name.split('.')[0]
  return { name, label, labelhash: labelhash(label), node: namehash(name), underParent: name === `${label}.${S.parent}` }
}

function setProfile(input) {
  let p = null
  if (input) {
    try { p = parseName(input); clearErr('name') } catch (e) { setErr('name', `“${input}” is not a valid ENS name`, e) }
  }
  S.profile = p
  const sec = $('profile')
  $('grid').classList.toggle('with-profile', !!p)
  sec.hidden = !p
  document.title = p ? `${p.name} · Met on ENS` : 'Met on ENS'
  renderFeed(false)
  if (S.booted) renderBoard(false)
  if (!p) { sec.innerHTML = ''; return }
  sec.innerHTML = `
    <a class="p-back" href="${esc(keepParams())}" data-nav="home">← all names</a>
    <div class="p-name">${p.underParent ? nameHtml(p.label) : esc(p.name)}</div>
    ${p.underParent ? '' : `<div class="p-notice">This name is not under ${esc(S.parent)}. Showing whatever its resolver returns.</div>`}
    <div class="stats">
      <div class="stat met"><div class="k">${KEYS.met}</div><div class="big v" id="pMet"><span class="none loading">…</span></div><div class="lbl">people met</div></div>
      <div class="stat"><div class="k">${KEYS.meetings}</div><div class="big v" id="pMt"><span class="none loading">…</span></div><div class="lbl">meetings</div></div>
      <div class="stat"><div class="k">${KEYS.zk}</div><div class="big v" id="pZk"><span class="none loading">…</span></div><div class="lbl">ZK verified</div></div>
    </div>
    <p class="desc" id="pDesc"><span class="k">description</span>…</p>
    <dl class="kv" id="pKv"></dl>
    <div class="links">
      <a href="${EXPLORER}/${esc(p.name)}/records" target="_blank" rel="noopener">Records on the ENS explorer ↗</a>
      <a href="${ENSAPP}/${esc(p.name)}" target="_blank" rel="noopener">ENS app ↗</a>
      ${S.cfg.appUrl ? `<a href="${esc(S.cfg.appUrl)}" target="_blank" rel="noopener">Start a meeting ↗</a>` : ''}
    </div>
    <h3 class="p-meet-h">Meetings</h3>
    <ol class="feed-list" id="pMeets"></ol>`
  if (S.booted) loadProfile(false)
}

async function loadProfile(animate) {
  const p = S.profile
  if (!p) return
  const reads = [
    ensText(p.name, KEYS.met), ensText(p.name, KEYS.meetings), ensText(p.name, KEYS.zk),
    ensText(p.name, 'description'), client.getEnsAddress({ name: p.name, strict: true }),
    S.reg && p.underParent ? client.readContract({ address: S.reg, abi: REG_ABI, functionName: 'getState', args: [BigInt(p.labelhash)] }) : Promise.resolve(null),
    S.resolver && p.underParent ? readMeet('countsOf', [p.labelhash]) : Promise.resolve(null),
  ]
  const [tMet, tMt, tZk, tDesc, tAddr, tState, tCounts] = await Promise.allSettled(reads)
  if (S.profile !== p) return
  const chain = tCounts.status === 'fulfilled' && tCounts.value ? { met: tCounts.value[1], meetings: tCounts.value[2], zk: tCounts.value[3] } : null
  const bigCell = (id, st) => {
    const el = $(id)
    if (el && setCell(el, st, animate)) flash(el.closest('.stat'), 'flash')
  }
  bigCell('pMet', pickCount(tMet, chain, 'met'))
  bigCell('pMt', pickCount(tMt, chain, 'meetings'))
  bigCell('pZk', pickCount(tZk, chain, 'zk'))

  const d = $('pDesc')
  const dk = '<span class="k">description</span>'
  if (tDesc.status === 'rejected') { d.className = 'desc muted'; d.innerHTML = `${dk}<span style="color:var(--err)">read failed · ${esc(errMsg(tDesc.reason))}</span>` }
  else if (!tDesc.value) { d.className = 'desc muted'; d.innerHTML = `${dk}No description record. The name is not registered, expired, or was revoked.` }
  else { d.className = 'desc'; d.innerHTML = `${dk}<q>${esc(tDesc.value)}</q>` }

  const kv = []
  if (tState.status === 'fulfilled' && tState.value) {
    const s = tState.value
    const until = Number(s.status) === 2 && Number(s.expiry) ? ` · until ${esc(dateFmt.format(new Date(Number(s.expiry) * 1000)))}` : ''
    kv.push(['status', `${esc(STATUS[s.status] || s.status)}${until}`])
    if (s.latestOwner && s.latestOwner !== ZERO) kv.push(['owner', `<a href="${ETHERSCAN}/address/${s.latestOwner}" target="_blank" rel="noopener">${esc(short(s.latestOwner, 8, 6))}</a>`])
  } else if (tState.status === 'rejected') kv.push(['status', `<span class="err">read failed · ${esc(errMsg(tState.reason))}</span>`])
  if (tAddr.status === 'fulfilled') kv.push(['addr()', tAddr.value ? `<a href="${ETHERSCAN}/address/${tAddr.value}" target="_blank" rel="noopener">${esc(short(tAddr.value, 8, 6))}</a>` : 'none · custodial, held by the PoP server key'])
  else kv.push(['addr()', `<span class="err">read failed · ${esc(errMsg(tAddr.reason))}</span>`])
  if (S.resolver) kv.push(['resolver', `<a href="${ETHERSCAN}/address/${S.resolver}" target="_blank" rel="noopener">MeetResolver ${esc(short(S.resolver, 8, 6))}</a>`])
  $('pKv').innerHTML = kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')
  renderProfileMeets(animate)
}

let pMeetIds = new Set()
function renderProfileMeets(animate) {
  const p = S.profile
  const el = $('pMeets')
  if (!p || !el) return
  const list = sortedMeets().filter((m) => m.nodeLo === p.node || m.nodeHi === p.node)
  if (!list.length) { el.innerHTML = `<li class="fi muted"><span class="pair">${S.scannedTo == null ? 'Reading logs…' : 'No meetings recorded yet.'}</span></li>`; return }
  el.innerHTML = list.slice(0, 30).map((m) => {
    const other = m.nodeLo === p.node ? m.nodeHi : m.nodeLo
    return meetItem(m, animate && !pMeetIds.has(m.id) ? 'newrow' : '', `<span class="x">⇄</span>${nodeLink(other)}`)
  }).join('')
  pMeetIds = new Set(list.map((m) => m.id))
}

// ---------- snapshot (optional web/snapshot.json)
async function loadSnapshot() {
  let snap
  try {
    const r = await fetch('snapshot.json', { cache: 'no-store' })
    if (!r.ok) return
    snap = await r.json()
  } catch { return }
  const sec = $('snapshot')
  const names = Array.isArray(snap.names) ? snap.names : []
  const meets = Array.isArray(snap.meetings) ? snap.meetings : []
  sec.hidden = false
  sec.innerHTML = `
    <h2>Verified snapshot <span class="seal">frozen</span></h2>
    <p class="fine">Recorded ${snap.takenAt ? esc(snap.takenAt) : ''}${snap.block ? ` at Sepolia block ${fmtInt(snap.block)}` : ''}${snap.resolver ? ` · MeetResolver <a href="${ETHERSCAN}/address/${esc(snap.resolver)}" target="_blank" rel="noopener">${esc(short(snap.resolver, 8, 6))}</a>` : ''}.
      Every transaction below is on Sepolia and can be checked on Etherscan even if ENS resets the v2 beta.</p>
    ${names.length ? `<div class="tw"><table><thead><tr><th>name</th><th>met</th><th>meetings</th><th>zk</th></tr></thead><tbody>
      ${names.map((n) => `<tr><td><a href="${EXPLORER}/${esc(n.name)}/records" target="_blank" rel="noopener">${esc(n.name)}</a></td><td>${esc(n.met ?? '')}</td><td>${esc(n.meetings ?? '')}</td><td>${esc(n.zk ?? '')}</td></tr>`).join('')}
    </tbody></table></div>` : ''}
    ${meets.length ? `<div class="tw"><table><thead><tr><th>meeting</th><th>hour</th><th>tx</th></tr></thead><tbody>
      ${meets.map((m) => `<tr><td>${esc(m.a || '')} ⇄ ${esc(m.b || '')}${m.firstTime === false ? ' (again)' : ''}</td><td>${m.timeBucket != null ? esc(hourLabel(m.timeBucket)) : ''}</td><td>${m.tx ? `<a href="${ETHERSCAN}/tx/${esc(m.tx)}" target="_blank" rel="noopener">${esc(short(m.tx, 10, 6))}</a>` : ''}</td></tr>`).join('')}
    </tbody></table></div>` : ''}`
}

// ---------- status + meta
function renderStatus(ok) {
  const dot = $('liveDot')
  if (ok === true) { dot.className = 'live-dot ok'; void dot.offsetWidth; dot.classList.add('tick') }
  if (ok === false) { dot.className = 'live-dot bad'; if (S.head == null) $('blockText').textContent = 'RPC unreachable' }
  tickClock()
}
function tickClock() {
  if (S.head != null) {
    const s = (Date.now() - S.headAt) / 1000
    $('blockText').textContent = `Sepolia #${fmtInt(S.head)}${s > 30 ? ` · ${ago(s)}` : ''}`
  }
  if (S.latestTs) $('justWhen').textContent = ago(Date.now() / 1000 - S.latestTs)
}
function renderMeta() {
  const addr = (a) => `<a href="${ETHERSCAN}/address/${a}" target="_blank" rel="noopener">${esc(short(a, 8, 6))}</a>`
  const items = [
    ['parent', `<a href="${EXPLORER}/${esc(S.parent)}" target="_blank" rel="noopener">${esc(S.parent)} ↗</a>`],
    ['resolver', S.resolver ? `${addr(S.resolver)} <span class="via">MeetResolver · ${esc(S.resolverVia)}</span>` : '—'],
    ['registry', S.reg ? `${addr(S.reg)}${S.deployBlock != null ? ` <span class="via">since block ${fmtInt(S.deployBlock)}</span>` : ''}` : '—'],
    ['reads', `viem 2.56.8 → Universal Resolver ${addr(sepolia.contracts.ensUniversalResolver.address)}`],
    ['rpc', esc(S.rpcLabel)],
  ]
  $('metaList').innerHTML = items.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')
}

// ---------- navigation
function go(name) {
  history.pushState(null, '', keepParams({ name }))
  setProfile(name)
  window.scrollTo({ top: $('grid').offsetTop - 12, behavior: 'smooth' })
}
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[data-name], a[data-nav="home"]')
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return
  e.preventDefault()
  if (a.dataset.nav === 'home') { history.pushState(null, '', keepParams()); setProfile(null) } else if (a.dataset.name) go(a.dataset.name)
})
window.addEventListener('popstate', () => setProfile(new URLSearchParams(location.search).get('name')))
$('searchForm').addEventListener('submit', (e) => {
  e.preventDefault()
  const v = $('searchInput').value.trim()
  if (v) go(v)
})

// theme: auto -> dark -> light -> auto
const THEMES = ['auto', 'dark', 'light']
function applyTheme(t) { if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t; $('themeBtn').title = `theme: ${t}` }
let theme = 'auto'
try { theme = localStorage.getItem('theme') || 'auto' } catch {}
applyTheme(theme)
$('themeBtn').addEventListener('click', () => {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % 3]
  applyTheme(theme)
  try { localStorage.setItem('theme', theme) } catch {}
})

// ---------- polling
let polling = false
async function poll() {
  if (polling) return
  polling = true
  try {
    const bn = await client.getBlockNumber({ cacheTime: 0 })
    if (S.head !== bn) { S.head = bn; S.headAt = Date.now() }
    clearErr('rpc')
    renderStatus(true)
    if (!S.resolver) {
      // Parent not set up yet (or ENS was reset): keep trying discovery.
      if (Date.now() - S.lastFull > 30000) { S.lastFull = Date.now(); await setupResolver() }
      return
    }
    if (S.scannedTo == null) return
    let touched = new Set()
    let newMembers = false
    let newMets = []
    if (bn > S.scannedTo) {
      const from = S.scannedTo - 2n > S.deployBlock ? S.scannedTo - 2n : S.deployBlock
      const r = await scan(from, bn, false)
      S.scannedTo = bn
      touched = r.touched; newMembers = r.newMembers; newMets = r.newMets
    }
    const full = Date.now() - S.lastFull > 60000
    if (full) { S.lastFull = Date.now(); touched = new Set(S.members.keys()) }
    if (touched.size) {
      await refreshCounts(touched)
      renderBoard(true)
    } else if (newMembers) renderBoard(true)
    if (newMets.length || touched.size) { renderFeed(true); await renderLatest(true) }
    if (S.profile && (touched.has(S.profile.node) || full)) await loadProfile(true)
    clearErr('poll')
  } catch (e) {
    setErr('poll', 'Live update failed (will retry)', e)
    renderStatus(false)
  } finally { polling = false }
}

async function setupResolver() {
  try {
    S.resolver = await discover()
    clearErr('discover')
  } catch (e) { setErr('discover', `Could not look up the resolver of ${S.parent}`, e); S.resolver = null }
  if (!S.resolver) { renderBoard(false); renderMeta(); if (S.profile) loadProfile(false); return false }
  try {
    const [db, reg, ev] = await Promise.allSettled([readMeet('DEPLOY_BLOCK'), readMeet('REG'), readMeet('eventName')])
    if (db.status === 'rejected') throw db.reason
    S.deployBlock = db.value
    if (reg.status === 'fulfilled') S.reg = reg.value
    if (ev.status === 'fulfilled' && ev.value) $('eventName').textContent = ev.value
    clearErr('setup')
  } catch (e) { setErr('setup', 'The resolver did not answer DEPLOY_BLOCK()', e); S.resolver = null; renderMeta(); return false }
  renderMeta()
  if (S.profile) loadProfile(false)
  try {
    const head = await client.getBlockNumber({ cacheTime: 0 })
    S.head = head; S.headAt = Date.now()
    await scan(S.deployBlock, head, true)
    S.scannedTo = head
    await refreshCounts(S.members.keys())
    S.lastFull = Date.now()
    clearErr('scan')
  } catch (e) { setErr('scan', 'Reading meeting logs failed', e) }
  renderBoard(false)
  renderFeed(false)
  await renderLatest(false)
  if (S.profile) renderProfileMeets(false)
  return true
}

// ---------- boot
async function boot() {
  let cfg = {}
  try { const r = await fetch('config.json', { cache: 'no-store' }); if (!r.ok) throw new Error(`HTTP ${r.status}`); cfg = await r.json() }
  catch (e) { setErr('config', 'config.json missing, using defaults', e) }
  S.cfg = { parent: 'enconomy.eth', rootRegistry: '', pollMs: 8000, appUrl: '', ...cfg }
  try { S.parent = normalize(qs.get('parent') || S.cfg.parent) } catch (e) { setErr('parent', 'Invalid parent name', e); S.parent = S.cfg.parent }
  S.parentNode = namehash(S.parent)
  $('parentName').textContent = S.parent
  if (S.cfg.eventName) $('eventName').textContent = S.cfg.eventName
  $('searchInput').placeholder = `alice.${S.parent}`

  const rpc = qs.get('rpc')
  const transport = rpc ? http(rpc, { batch: true }) : fallback([http(DEFAULT_RPCS[0], { batch: true }), http(DEFAULT_RPCS[1]), http(DEFAULT_RPCS[2])])
  S.rpcLabel = rpc ? `custom ${rpc}` : 'publicnode → tenderly → 1rpc'
  client = createPublicClient({ chain: sepolia, batch: { multicall: true }, transport })
  renderMeta()

  setProfile(qs.get('name'))
  loadSnapshot()
  checkRoot()
  await setupResolver()
  S.booted = true
  if (S.profile) renderBoard(false)
  setInterval(poll, Math.max(3000, Number(S.cfg.pollMs) || 8000))
  setInterval(tickClock, 1000)
  poll()
}

boot().catch((e) => setErr('boot', 'Page failed to start', e))
