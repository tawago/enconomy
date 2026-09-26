# Deployments: Ethereum Sepolia (11155111)

2026-09-27, block 11,787,131. Deployer `0x7Dc35E0c67Bd247f61f3cc5053a16E4FC94e8860` (shared with the ENS lane). Source verified on Sourcify (`exact_match`). Etherscan isn't verified because no API key is available. Machine-readable: `deployments/11155111.json`, `deployments/demo-11155111.json`.

## Contracts

| contract | address | tx |
|---|---|---|
| PopAttestationVerifier (presence verifier, `pop-safe-v2`) | `0xD9E2F407424a7422E195d034ECc4fC932120d96F` | `0xb45ae7f93c4011bbdadaa23be3441ca15f8c9155446964b3077356df8d4a824f` |
| PopSafeGuard (verifier = above, immutable) | `0x1e0AD6528e6769508A241b78b73A6F9b1342bb3B` | `0xce485430454eb2712dd95ecd3add764b2e664da62d5a176f190c77f3006cdaaf` |
| PopSafeSetup | `0x3d4e549F13CCee540884481b35Fd1CA42A9E0707` | `0x8081bd0ebfbd8747f8cdaf56f7b93fb74d3cb35c3800bc45dd8367dac5566ac9` |
| P256OwnerFactory | `0x99565991Ec5414Ee2d3A2fA48Ab4d92efBd2466e` | `0x1321eb91a8cc4c635d5707362c2d249630289a1c1d6f8c3e50c8742127c1b9cf` |

Safe: canonical 1.5.0 SafeL2 `0xEdd160fEBBD92E350D4D398fb636302fccd67C7e` via SafeProxyFactory `0x14F2982D601c9458F93bd70B218933A6f8165e7b`.

## Demo Safe (test keys, not real phones)

2-of-4 Safe `0x1399D5F9B91B92EF8220E9328743Ac5F370Ed6d4`. Fallback handler is `0`. Guard set inside setup. Hatch delay is 300 s, grace 600 s.

| owner | address | key |
|---|---|---|
| P256Owner phone A | `0xB1A1A99912f962F33CF9E9716a4F920AAb2D6056` | dev P-256 `PHONE_A_KEY` (`.env.demo`) |
| P256Owner phone B | `0x6Ff3751bEBB89707cD05186F1c67C8530D6FD180` | dev P-256 `PHONE_B_KEY` (`.env.demo`) |
| guardian 1 | `0x1291992a1BE4e3b37e1fB5423a22dC2379b94FDb` | `G1_PK` (`.env.guardians`) |
| guardian 2 | `0xD2f5b64C51369E1158cD6ad56d6358407Bc3D3De` | `G2_PK` (`.env.guardians`) |

Issuer (attester) key is a **dev key** (`ISSUER_KEY` in `.env.demo`), not the server's. The server doesn't sign `pop-safe-v2` yet.
- X `0xe456d477fdff5a857ea08d43beaf5a342675d558321930a44c610b75944d8242`
- Y `0x08f1c0b3d93980977ff941d64044e361d264759b50082bbe3058f33537ed60e8`

To use the server's key later, do one of these: load the dev key into the server's `pop-safe-v2` signer, rotate the issuer through the hatch (`Recover.s.sol`), or create a new Safe.

| step | tx | result |
|---|---|---|
| owner A (`factory.deploy`) | `0xe4240818845a9ec3449f2e47b76a827c3fe53eb72833a5d85563c8780559452d` | ok |
| owner B (`factory.deploy`) | `0xf9ed632d5e12c3be5ab71e0aeee6e4c3eb60e17de3aa80bd17d0500346887dc5` | ok |
| create Safe (`createProxyWithNonce`, salt 1) | `0x2089e624c678a96159750555712bb02985758231a67a932b2140b6f2cde30c85` | ok |
| fund 0.002 ETH | `0x432c430b2d93c97eb0ecbb35dfeb11efd33f53a6aa18591736c281ed361d4e49` | ok |
| **presence spend**: 0.0005 ETH to `0x…b0b0`, phones A+B sign, POP2 attestation | `0x137acc8f278f0477f4be6e0d812cf51ba1d865d063263e70e5fc42e5c6ce90d6` | **success**, 157,502 gas |
| **no-presence spend**: guardians G1+G2 sign the same spend, no presence | `0x31aa9d7b068b3ec0a21b6639ab5c1579ae4876dcb402c4a3bc9deb73c86ab885` | **reverted** (`NoPresence`, checked by `eth_call` before sending) |

Reproduce with `script/sepolia_demo.sh`. For a dry run on an anvil fork: `RPC=http://127.0.0.1:8612 OUT_TAG=anvil-11155111 SALT=$(date +%s) script/sepolia_demo.sh`.

Explorer: https://sepolia.etherscan.io/address/0x1399D5F9B91B92EF8220E9328743Ac5F370Ed6d4
