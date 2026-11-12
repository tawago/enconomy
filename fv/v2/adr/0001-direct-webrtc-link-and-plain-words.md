# ADR 0001: a direct WebRTC link, no server in a run, and plain words

Date: 2026-11-11. Status: accepted by the owner, except the rows marked "proposed" in the word table. Nothing here is built or tested.

Decision 2 is amended by [ADR 0002](0002-plain-names-in-the-lean-models.md): the Lean rule model gets new names, and Lean theorem names say what they prove.

This record changes the v2 design in [`fv/v2/spec.md`](../spec.md). It holds two decisions. The first replaces the mailbox server with a direct link between the two devices. The second replaces words in the specs that were hard to read.

## Context

The v2 draft removed the v1 server but kept a "mailbox". The mailbox was a small server that forwarded messages between the two devices. It decided nothing, and the spec treated it as controlled by the attacker. Two problems came up.

- The mailbox was still a server that somebody has to run, and every run needed it.
- The name hid that. "Serverless, over a mailbox" read as if no server existed.

The owner set these requirements on 2026-11-11.

- No server takes part in a run.
- A browser must be able to take part.
- The target runs are phone with phone and phone with browser. Browser with browser is not a target for now.

## Decision 1: the devices talk over a direct WebRTC data channel

The cost comes first. The design uses no STUN server and no TURN server, so both devices must be on the same local network. Two phones with no shared Wi-Fi need one of them to open a hotspot. If the link closes during a run, the session ends, and a new link needs new QR codes.

The link is set up with one QR code in each direction.

1. Device A shows a QR code. It holds the `INVITE` of the spec (A's public key, A's random bytes, the context) and, next to it, A's WebRTC offer.
2. Device B scans it and shows a QR code back. It holds the `JOIN` of the spec (both keys, both randoms, the context, signed by B) and, next to it, B's WebRTC answer. The `JOIN` used to travel through the mailbox.
3. Device A scans it and the data channel opens. Every later message travels on the channel.

The offer and the answer are not part of `INVITE` or `JOIN`. They are not signed and not in the log, so the log holds no network address.

A laptop in a run needs a camera, because it has to scan the phone's QR code.

The channel is reliable and ordered, and WebRTC encrypts it. Each offer and answer carries the certificate fingerprint of its device. So a third device on the network can't take over the channel without changing a QR code.

"No server" covers a run. Two things stay outside it.

- A browser loads the web app from a static host before the run. That host takes no part in the run, but whoever controls it controls the code the browser runs.
- The browser has no ZK prover today. In a phone with browser run only the phone can attach a proof.

### What changes in the protocol

- The mailbox party is gone. The spec has a link in its place.
- Both keys now travel by QR code. Before, A received B's key through the mailbox and relied on the confirm tap. This closes hole K6. The out-of-band assumption now has to cover both QR codes.
- The spec no longer encrypts payloads itself, because WebRTC does it. This replaces the ECDH step of question Q13.
- Hole K15 said the mailbox sees who talks to whom. No third party carries the messages now. Someone on the same network still sees two local addresses exchange encrypted packets.

### What does not change

- Every message rule stays: the signed common form, the checks on receipt, one message per slot, the drop rules, resend and the `peer` field. On a reliable link a resend only matters for a message the partner dropped as "not expected yet", such as one that arrived before the confirm tap.
- `sid` is computed as before. The WebRTC fingerprints are not part of it, and no property depends on the channel being secure.
- FP1 to FP6 and every Lean theorem statement stay. The Lean model already lets the attacker choose every incoming message and its order. A reliable, ordered link is a special case of that.
- The link is not evidence that the devices are close, because radio can be forwarded. The sound still has to carry the distance claim.

### Not tested

None of this has run. These points need a test before device work starts (roadmap stage 5).

- Whether a WebRTC offer and answer, cut down to the fields the other side needs, fit in a QR code that a phone camera reads fast.
- Whether a browser gives out its real local address. Browsers can hide it behind an mDNS name, and the phone app may not resolve that name.
- Whether the Wi-Fi at a venue lets two devices reach each other. Guest networks often block it.
- Whether a phone hotspot works as the fallback, on Android and on iPhone.
- Android with iPhone, and a phone with a laptop browser.
- Pairing by NFC tap, which v1 has. It would have to carry both payloads.

### Options not taken

- Keep the forwarding server. It works on any network, but it is a server in every run.
- Bluetooth LE. It needs no network, but Safari and Firefox have no Bluetooth, so it fails the browser requirement.
- Public relays such as Nostr or Waku. We would run nothing, but servers would still carry every message.
- WebRTC with a STUN server. It would connect devices on different networks in many cases. It is a server, so it is left out. It can be added later without a protocol change.

## Decision 2: words

The v2 specs and the Lean protocol model use the new words from now on.

| Old | New | Status |
|---|---|---|
| mailbox | removed. The carrier is "the link" | agreed |
| half | gap: the number of samples from A's sound to B's sound in a device's own recording | agreed |
| record | log: the list of signed messages of one session | agreed |
| commit, then reveal or open | send the hash, then send the value | agreed |
| rule R2 | the detection rule, or "the v2 rule" where the v1 rule is nearby | agreed |
| `SEEDC` | `SEED_HASH` | proposed |
| `REVEAL` | `SEED_VALUE` | proposed |
| `RECC` | `REC_HASH` | proposed |
| `TXC` | `GAP_HASH` | proposed |
| `TXO` | `GAP_VALUE` | proposed |
| a value "opens" a hash | a value "matches" a hash | proposed |
| `fp2_opens`, `fp6_txo_opens`, `txOk_opens` | `fp2_matches`, `fp6_gap_matches`, `txOk_matches` | proposed |
| `fp1_recc_clock`, `fp3_after_txc`, `fp6_txo_fixed` | `fp1_rec_hash_clock`, `fp3_after_gap_hash`, `fp6_gap_fixed` | proposed |

The message names follow one pattern. A device sends `X_HASH` first and `X_VALUE` later. The recording has a hash message and no value message, because the recording is never sent. `GAP_VALUE` carries the signed transcript, which holds the gap.

Rules for the swap.

- Wire and code names stay: the POPT field `half`, `code_commit`, `commit_hash`, `rec_root`, `verify_record`, POPC and POPT. The spec says once that the gap is the POPT field `half`.
- Ids stay: FP1 to FP6, K1 to K16, Q1 to Q20, RC, RS, RT, and the C, CN and FN ids from v1. Each id keeps its plain name next to it.
- These words stay as they are: seed, salt, blind, attempt, transcript, reader, verdict, `SALT`, `TIME`, `FAIL`, `INVITE`, `JOIN`.
- v1 documents keep their words, because they describe the system as built. Only Part 2 of `fv/v1/informal-spec.md` gets a pointer to this record.
- The Lean protocol model uses `seedHash`, `seedVal`, `recHash`, `gapHash`, `gapVal`, `gap` and `Log`. The Lean rule model changes in comments only.
