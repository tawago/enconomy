# Changelog

## 2026-04-30 v5c - Chirp alignment + full MFCC

**Problem with v5b:** Reverb-only approach gave 16% disagreement.
Reverb tail is too quiet, low SNR, noise dominates.

**Solution:** Use chirp for precise alignment, but extract MFCC from full 2s segment:
1. Find chirp position via cross-correlation (precise timing)
2. Align both recordings to chirp start
3. Extract 2 seconds of audio from chirp start
4. Apply proven MFCC feature extraction to aligned audio

**Rationale:** Chirp gives precise alignment (better than cross-correlation of full audio). Then use the working MFCC approach on aligned audio.

---

## 2026-04-30 v5b - Reverb tail MFCC approach (16% disagreement)

**Problem:** Reverb tail too quiet, noise dominates.

---

## 2026-04-30 v5 - Chirp + Room Impulse Response

**Problem:** Ambient audio matching doesn't provide proximity proof.

**Solution:** Chirp + room acoustics approach (FAILED - 30% disagreement)

**Issue:** Deconvolution produces different results for direct vs room-filtered sound.

---

## 2026-04-30 v4 - Per-coefficient normalization

**Problem:** 8-10% disagreement with v2/v3, barely missing t=50 threshold.

**Key insight from testing:**
- Hamming distance increases when quieter (noise dominates)
- Distance does NOT increase with physical distance (audio uniform in room)
- Proximity proof needs different approach (emitted signal, ultrasonic, etc.)

**Changes (Approach 2):**
- Z-score normalize each MFCC coefficient independently
- Remove device-specific biases
- Use shape features: percentiles, skewness proxy, kurtosis proxy
- Add zero-crossing rate of normalized coefficients
- Simplified delta features with sign of direction

**Expected:** Lower disagreement by removing mic-specific biases.

---

## 2026-04-30 v3 - Increase BCH error correction

**Goal**: Validate if approach works at all with higher error tolerance.

**Changes:**
- BCH m=10, t=60 (was m=9, t=15)
- 1080 bits total, can correct up to 60 bit errors
- 60 bytes secret capacity (was 47 bytes)

**Expected**: Same-room trials with ~50 bit Hamming distance should now pass.

---

## 2026-04-30 v2 - Feature extraction improvements

**Problem:** Same-room recordings showing 40-107 bit Hamming distance (8-21%), far exceeding BCH threshold of t=15.

**Analysis findings (from analyze_audio.py):**
- 187ms timing lag between device recordings
- MFCC[0] (energy) differs by 138 - device mic gain varies
- Spectral features (centroid, rolloff, ZCR, RMS) diverge massively (3000+ difference)
- Cross-correlation only 0.605

**Changes:**
1. Add time-alignment using cross-correlation before feature extraction
2. Drop MFCC[0] - volume/energy is device-dependent
3. Remove spectral features (centroid, rolloff, ZCR, RMS) - too mic-sensitive
4. Keep delta MFCCs - temporal changes more stable than absolute values

**Expected outcome:** Reduce Hamming distance for same-room recordings.

---

## 2026-04-30 v1 - Initial implementation

- MFCC extraction (13 coefficients)
- Summary stats: mean, std, percentiles, delta mean/std
- Delta and delta-delta MFCCs
- Spectral features: centroid, rolloff, ZCR, RMS
- BCH(m=9, t=15) - 512 bits, corrects up to 15 errors
- Result: 40-107 bit disagreement for same-room → all trials failed
