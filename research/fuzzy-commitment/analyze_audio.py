"""Analyze audio pairs to understand feature divergence."""

import sys
import numpy as np
import librosa
import soundfile as sf
from pathlib import Path
from audio_features import (
    load_audio, normalize_duration, normalize_amplitude,
    extract_mfcc_features, quantize_to_bits, get_target_bits,
    TARGET_SR, N_MFCC
)

def analyze_pair(file_a: Path, file_b: Path):
    """Compare two audio files in detail."""

    # Load raw audio
    audio_a = load_audio(file_a.read_bytes())
    audio_b = load_audio(file_b.read_bytes())

    print(f"\n=== Audio Comparison ===")
    print(f"File A: {file_a.name}")
    print(f"File B: {file_b.name}")

    # Basic stats
    print(f"\nRaw lengths: A={len(audio_a)} B={len(audio_b)} samples")
    print(f"Duration: A={len(audio_a)/TARGET_SR:.2f}s B={len(audio_b)/TARGET_SR:.2f}s")

    # Normalize
    audio_a = normalize_duration(audio_a)
    audio_b = normalize_duration(audio_b)
    audio_a = normalize_amplitude(audio_a)
    audio_b = normalize_amplitude(audio_b)

    # Cross-correlation to check timing alignment
    corr = np.correlate(audio_a, audio_b, mode='full')
    lag = np.argmax(corr) - len(audio_a) + 1
    max_corr = np.max(corr) / (np.std(audio_a) * np.std(audio_b) * len(audio_a))
    print(f"\nCross-correlation: peak={max_corr:.3f}, lag={lag} samples ({lag/TARGET_SR*1000:.1f}ms)")

    # RMS energy comparison
    rms_a = np.sqrt(np.mean(audio_a**2))
    rms_b = np.sqrt(np.mean(audio_b**2))
    print(f"RMS energy: A={rms_a:.4f} B={rms_b:.4f} ratio={rms_a/rms_b:.2f}")

    # MFCC comparison
    mfcc_a = librosa.feature.mfcc(y=audio_a, sr=TARGET_SR, n_mfcc=N_MFCC)
    mfcc_b = librosa.feature.mfcc(y=audio_b, sr=TARGET_SR, n_mfcc=N_MFCC)

    print(f"\n=== MFCC Comparison (per coefficient) ===")
    print(f"{'Coef':<6} {'Mean A':<10} {'Mean B':<10} {'Diff':<10} {'Corr':<10}")

    for i in range(N_MFCC):
        mean_a = np.mean(mfcc_a[i])
        mean_b = np.mean(mfcc_b[i])
        diff = abs(mean_a - mean_b)
        corr = np.corrcoef(mfcc_a[i], mfcc_b[i])[0, 1]
        print(f"{i:<6} {mean_a:<10.2f} {mean_b:<10.2f} {diff:<10.2f} {corr:<10.3f}")

    # Feature vector comparison
    features_a = extract_mfcc_features(audio_a)
    features_b = extract_mfcc_features(audio_b)

    print(f"\n=== Feature Vector Comparison ===")
    print(f"Feature vector length: {len(features_a)}")

    # Find most divergent features
    diffs = np.abs(features_a - features_b)
    top_divergent = np.argsort(diffs)[-10:][::-1]

    print(f"\nTop 10 most divergent features:")
    print(f"{'Index':<8} {'Value A':<12} {'Value B':<12} {'Diff':<12}")
    for idx in top_divergent:
        print(f"{idx:<8} {features_a[idx]:<12.4f} {features_b[idx]:<12.4f} {diffs[idx]:<12.4f}")

    # Bit comparison
    bits_a = quantize_to_bits(features_a)
    bits_b = quantize_to_bits(features_b)

    hamming = np.sum(bits_a != bits_b)
    print(f"\n=== Bit Vector Comparison ===")
    print(f"Total bits: {len(bits_a)}")
    print(f"Hamming distance: {hamming} ({hamming/len(bits_a)*100:.1f}%)")

    # Which bit ranges disagree most?
    chunk_size = 64
    print(f"\nDisagreement by {chunk_size}-bit chunks:")
    for i in range(0, len(bits_a), chunk_size):
        chunk_diff = np.sum(bits_a[i:i+chunk_size] != bits_b[i:i+chunk_size])
        pct = chunk_diff / min(chunk_size, len(bits_a) - i) * 100
        bar = '#' * int(pct / 5)
        print(f"  bits {i:3d}-{min(i+chunk_size-1, len(bits_a)-1):3d}: {chunk_diff:2d} ({pct:5.1f}%) {bar}")


if __name__ == '__main__':
    audio_dir = Path(__file__).parent / 'audio'

    if len(sys.argv) == 3:
        # Compare specific files
        analyze_pair(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        # Find most recent trial pair
        files = sorted(audio_dir.glob('*.wav'), key=lambda f: f.stat().st_mtime, reverse=True)
        if len(files) >= 2:
            # Group by trial_id (first part of filename)
            trial_id = files[0].name.split('_')[0]
            pair = [f for f in files if f.name.startswith(trial_id)]
            if len(pair) == 2:
                analyze_pair(pair[0], pair[1])
            else:
                print("Could not find matching pair")
        else:
            print("Not enough audio files")
