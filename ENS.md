# ENS: Met on ENS (PR #1)

Every meeting proven by the PoP server becomes onchain ENS records on Ethereum Sepolia (ENSv2).

## Live

| | |
|---|---|
| Web page | https://enconomy.dev (profile: https://enconomy.dev/?name=alice.enconomy.eth) |
| ENS records | https://explorer.ens.dev/alice.enconomy.eth/records |
| PoP server | https://pop.enconomy.dev (Cloudflare tunnel to the laptop server) |
| MeetResolver | [`0xfc300a640ccdEFF0e61f7875D55A9Cd22eb51346`](https://sepolia.etherscan.io/address/0xfc300a640ccdEFF0e61f7875D55A9Cd22eb51346) (resolver for `enconomy.eth` + `*.enconomy.eth`) |
| PhoneVerifier | [`0x5b69C5a7D3e5A56D33809b9B95d02984D4aFa791`](https://sepolia.etherscan.io/address/0x5b69C5a7D3e5A56D33809b9B95d02984D4aFa791) |
| PairVerifier | [`0xfFA0cf3d79E2a27bC11b9E67eDB979a9b5BE3Fd7`](https://sepolia.etherscan.io/address/0xfFA0cf3d79E2a27bC11b9E67eDB979a9b5BE3Fd7) |
| VerifyLog | [`0x53D6DB2580466FeE5F07c4Bb7b4c07C41797B996`](https://sepolia.etherscan.io/address/0x53D6DB2580466FeE5F07c4Bb7b4c07C41797B996) |

Each name's `url` text record is `https://enconomy.dev/?name=<label>.enconomy.eth` (site set in [this `setSite` tx](https://sepolia.etherscan.io/tx/0xec083cad994007bfd6ee3abd78f2ce81822d1d24224a10b825e8368d09948ba9)).

## ZK fixture verified onchain

Fixture `180ca04b_48k`, UltraHonk (bb v5 nightly, keccak transcript):

- phone A: [0xdfcf35fa…9774](https://sepolia.etherscan.io/tx/0xdfcf35fac50c90c2a84e071e7ff780221304b495e7a8f047050e846340cd9774)
- phone B: [0x081a3b23…1968](https://sepolia.etherscan.io/tx/0x081a3b2300619eece6774069bde33b7de4cafcc8aa6c47ea816f2327275f1968)
- pair: [0xb065f2ff…c5a8](https://sepolia.etherscan.io/tx/0xb065f2ff3324d288631067c36198f6ed08ebd3142167f91954859eb8e695c5a8)

## Where things live

- `contracts/` — MeetResolver, `script/ens.sh` bootstrap/ops, `deployments/sepolia.json`, `deployments/zk-sepolia.json`
- `bridge/` — watcher: PoP server results -> MeetResolver + verifier txs
- `web/` — the page; `npx wrangler deploy` from the repo root (`wrangler.jsonc`)
