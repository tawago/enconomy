# web: Met on ENS

Static demo page. Reads Ethereum Sepolia (ENSv2) directly with viem 2.56.8 from jsDelivr. No build step, no backend; works with the PoP server off.

Files: `index.html`, `app.js`, `style.css`, `config.json`, `assets/` (project art as webp), optional `snapshot.json`.

Look: colours sampled from the project art. Lime = people and names, blue = sound and the live proof moment, pink = errors and voided meetings, orange = small accents. Dark mode is the navy of the bouncer scene.

## What it does

- Parent name from `config.json` (`enconomy.eth`) or `?parent=`.
- Finds the MeetResolver with `getEnsResolver(parent)` through the Universal Resolver. Fallback: `RootRegistry.getSubregistry("eth")` → `ETHRegistry.getResolver(label)`. Any candidate must answer `DEPLOY_BLOCK()`.
- Leaderboard: `Member` + `Met` (+ `ZkVerified`, `MeetVoided`) logs from `DEPLOY_BLOCK` in 45,000-block chunks. Counts come from ENS text records (`getEnsText`, `strict: true`) and are cross-checked with `countsOf`; a disagreement shows as "chain N" under the value. Names whose `countsOf` says not registered are hidden.
- Profile: `?name=alice` or `?name=alice.enconomy.eth`, or the search box. Shows met / meetings / zk, `description`, registry status + expiry + owner, `addr()`, meetings (partner + hour from `timeBucket`), links to explorer.ens.dev and Etherscan.
- Header totals: live meetings (not voided) and names on the board.
- Live: polls every `pollMs` (default 8 s). When a meeting lands, the "Latest meeting" card swaps to the new pair and glows, each count that went up rolls N → N+1 with a "+1" pill, the row washes accent and slides to its new rank, and the meeting drops into the feed (latest 8). All steps chain on `animationend`, so pausing the page's animations freezes the moment for a screenshot.
- Chain details (parent, resolver, registry, deploy block, UR, RPC) sit in the footer.
- Errors (RPC failure, UR revert) are shown as errors, never as empty values. An empty text record shows "—".
- Banner when `UR.ROOT_REGISTRY()` differs from `config.json` `rootRegistry` (ENS redeployed the beta).

## Query params

| Param | Use |
|---|---|
| `name` | Profile view |
| `parent` | Other parent 2LD |
| `rpc` | Single RPC instead of publicnode → tenderly → 1rpc, e.g. a local anvil fork: `?rpc=http://127.0.0.1:8545` |
| `resolver` | Skip discovery and use this MeetResolver address (testing before the parent is set up) |

## Preview locally

```
cd web && python3 -m http.server 8787
open http://127.0.0.1:8787/
open "http://127.0.0.1:8787/?name=alice"
```

Against a fork: `anvil --fork-url https://ethereum-sepolia-rpc.publicnode.com`, deploy + bootstrap there, then `?rpc=http://127.0.0.1:8545` (add `&resolver=0x…` if the parent's resolver is not set on the fork).

## Deploy (Cloudflare Workers)

Live: https://ens.enconomy.dev (Workers static-assets site `enconomy`, custom domain, workers.dev off). The apex https://enconomy.dev still routes to the same worker but is reserved for a future landing page; link to `ens.enconomy.dev`. Config in `/wrangler.jsonc`; from the repo root:

```
npx wrangler deploy
```

No build step. The MeetResolver `siteUrl` is `https://ens.enconomy.dev/`, so each name's `url` record is `https://ens.enconomy.dev/?name=<label>.enconomy.eth`. To move it: `ENS_SITE_URL=<url> ./contracts/script/ens.sh bootstrap` (one `setSite` tx). Caveat (2026-09-27): a fresh `forge build` predicts a different MeetResolver address than the deployed `0xfc30…1346`, so bootstrap would deploy a new resolver and repoint the 2LD. Until that is fixed, move the site with a direct `cast send <meetResolver> 'setSite(string,string)' "ETHGlobal Tokyo 2026" <url>` (how the move to `ens.enconomy.dev` was done).

## snapshot.json (optional)

Before submission, freeze the demo state so judges can check it even after an ENS reset. Rendered as "Verified snapshot" when the file exists.

```json
{
  "takenAt": "2026-09-27T06:00:00Z",
  "block": 11790000,
  "resolver": "0x…",
  "names": [{ "name": "alice.enconomy.eth", "met": 5, "meetings": 6, "zk": 1 }],
  "meetings": [{ "a": "alice.enconomy.eth", "b": "bob.enconomy.eth", "tx": "0x…", "block": 11789999, "timeBucket": 493200, "firstTime": true }]
}
```
