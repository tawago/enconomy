# ETHGlobal Mumbai research

Start with `evp-recovery/2026-11-06-progress-report.md`.

| Folder | What it is |
| --- | --- |
| `evp-recovery/` | Key recovery by email, a registered laptop and a proximity proof, in one frame tx |
| `poc-evp-issuer/` | The EVP token verifier that `evp-recovery/live-chrome` links to |
| `poc-validation-rules/` | The frame account contracts EVP recovery started from |
| `poc-verifier-gas/` | Measured gas cost of proof verifiers |
| `poc-phone-signing/` | Raw-digest P-256 signing for the new phone's key, not yet tested on phones |
| `poc/clients/` | Frame tx library and devnet tools |
| `devnet/` | Our own sidecar for chain 1337, with a raised verify limit and precompiles allowed |
| `notes/` | Notes on EIP-8141, the alt mempool and EVP |

Some notes mention things that aren't in this repo: earlier planning notes (`00` to `09`, `2026-11-02-*`), the devnet findings (`2026-11-05-*`), the ENS spikes (`ens-half`, `ens-oracle-1337`), `poc/dnssec-gas`, `stretch-human-lane`, and the ChirpGas code. We decided not to use them, so those references are history only.
