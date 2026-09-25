# Fuzzy Commitment Audio Validation MVP

A browser-based research tool to validate whether ambient audio can produce stable binary features for fuzzy commitment schemes.

## Purpose

Test whether two devices recording the same room produce bit vectors close enough for BCH error correction (t=31), while different rooms stay far enough apart to reject.

## Setup

```bash
cd research/fuzzy-commitment
pip install -r requirements.txt
python server.py
```

## Usage

1. Open `http://<your-ip>:5000` on two devices (laptop + phone)
2. Grant microphone permission on both
3. Wait for "Peer: Connected" status
4. Enter a condition label (e.g., "same-room-desk")
5. Press "Start Test" on the initiator device
6. Both devices record simultaneously and upload
7. View results: Hamming distance, BCH decode success, key match

## Experiment Protocol

### Same-Environment Trials (expect success)
- Same desk, 10 trials
- Same room ~2m apart, 10 trials  
- Same room with obstruction, 10 trials

### Different-Environment Trials (expect failure)
- Different rooms, 10 trials
- Same room, different times with ambient changes, 10 trials
- One device near TV/music, other quiet, 10 trials

## Interpreting Results

| Metric | Meaning |
|--------|---------|
| Hamming Distance | Bit differences between feature vectors |
| Disagreement % | Hamming / 511 × 100 |
| BCH Threshold | Max correctable errors (t=31) |
| Reproduce Success | BCH decode succeeded |
| Key Match | Decoded secret matches original |

### Success Criteria
- Same-room: ≥80% key match rate
- Different-room: 0% key match rate
- Same-room Hamming: clustered below 31
- Different-room Hamming: clustered above 31

## Decision Framework

After running experiments:

1. **Proceed**: Clear separation between same/different room distributions
2. **Retune**: Overlap exists but adjusting t, quantization, or preprocessing could fix it
3. **Rework**: MFCC-to-bits approach is fundamentally unstable
4. **Stop**: Distributions overlap too heavily to be practical

## Files

- `server.py` - Flask + SocketIO coordinator
- `audio_features.py` - MFCC extraction, 511-bit quantization
- `bch_codec.py` - BCH(511, k, t=31) wrapper
- `fuzzy_commitment.py` - Commitment generation/reproduction
- `trial_logger.py` - JSONL trial logging
- `logs/trials.jsonl` - Experiment data (created on first run)
- `audio/` - Raw recordings (created on first run)
