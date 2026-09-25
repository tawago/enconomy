"""Deterministic audio feature extraction and quantization."""

import numpy as np
import librosa
import soundfile as sf
from io import BytesIO

TARGET_SR = 16000
TARGET_DURATION = 2.5
TARGET_SAMPLES = int(TARGET_SR * TARGET_DURATION)
N_MFCC = 13
N_FFT = 2048
HOP_LENGTH = 512

# Room impulse response parameters
CHIRP_DURATION = 0.2  # 200ms chirp
CHIRP_F0 = 500  # Start frequency Hz
CHIRP_F1 = 4000  # End frequency Hz
IR_EARLY_MS = 50  # Early reflections window (ms)
IR_ANALYSIS_MS = 500  # Total IR analysis window (ms)


def get_target_bits():
    from bch_codec import BCHCodec
    return BCHCodec().n_bits


def load_audio(audio_data: bytes) -> np.ndarray:
    """Load audio from WAV bytes, convert to mono, resample to target rate."""
    audio, sr = sf.read(BytesIO(audio_data))
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    if sr != TARGET_SR:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
    return audio.astype(np.float32)


def normalize_duration(audio: np.ndarray) -> np.ndarray:
    """Trim or zero-pad to exactly target duration."""
    if len(audio) > TARGET_SAMPLES:
        audio = audio[:TARGET_SAMPLES]
    elif len(audio) < TARGET_SAMPLES:
        audio = np.pad(audio, (0, TARGET_SAMPLES - len(audio)), mode='constant')
    return audio


def normalize_amplitude(audio: np.ndarray) -> np.ndarray:
    """Normalize to [-1, 1] range deterministically."""
    max_val = np.max(np.abs(audio))
    if max_val > 1e-6:
        audio = audio / max_val
    return audio


def generate_chirp(seed: int, sample_rate: int = TARGET_SR) -> np.ndarray:
    """Generate deterministic chirp: 500Hz to 4000Hz sweep over 200ms.

    Uses seed for reproducibility so both devices generate identical chirps.
    """
    np.random.seed(seed)
    n_samples = int(CHIRP_DURATION * sample_rate)
    t = np.linspace(0, CHIRP_DURATION, n_samples, dtype=np.float32)

    # Linear frequency sweep (chirp)
    # Instantaneous frequency: f(t) = f0 + (f1 - f0) * t / duration
    # Phase: integral of 2*pi*f(t) dt
    phase = 2 * np.pi * (CHIRP_F0 * t + (CHIRP_F1 - CHIRP_F0) * t**2 / (2 * CHIRP_DURATION))
    chirp = np.sin(phase).astype(np.float32)

    # Apply Tukey window to avoid clicks at start/end
    window = np.ones(n_samples, dtype=np.float32)
    taper_samples = int(0.01 * sample_rate)  # 10ms taper
    taper = 0.5 * (1 - np.cos(np.pi * np.arange(taper_samples) / taper_samples))
    window[:taper_samples] = taper
    window[-taper_samples:] = taper[::-1]

    return chirp * window


def extract_room_response(audio: np.ndarray, chirp: np.ndarray) -> np.ndarray:
    """Extract room impulse response using cross-correlation/deconvolution.

    The impulse response shows how the room "colored" the chirp.
    Uses Wiener deconvolution for noise robustness.
    """
    # Zero-pad chirp to match audio length for FFT
    n = len(audio)
    chirp_padded = np.zeros(n, dtype=np.float32)
    chirp_padded[:len(chirp)] = chirp

    # FFT-based deconvolution with regularization (Wiener)
    Audio_fft = np.fft.rfft(audio)
    Chirp_fft = np.fft.rfft(chirp_padded)

    # Wiener deconvolution: H = (S* * Y) / (|S|^2 + noise)
    # noise estimate as small fraction of signal power
    noise_power = 0.01 * np.mean(np.abs(Chirp_fft)**2)
    H = (np.conj(Chirp_fft) * Audio_fft) / (np.abs(Chirp_fft)**2 + noise_power)

    impulse_response = np.fft.irfft(H, n=n).astype(np.float32)
    return impulse_response


def extract_room_features(audio: np.ndarray, chirp_seed: int) -> np.ndarray:
    """Extract room acoustic features from chirp recording.

    Features capture how the room affects sound propagation:
    - Early reflection patterns (first 50ms)
    - Reverb decay characteristics
    - Frequency-dependent decay

    Two devices in the same room will have similar features;
    relayed audio won't capture local room acoustics.
    """
    chirp = generate_chirp(chirp_seed, TARGET_SR)

    # Find chirp location via cross-correlation
    correlation = np.correlate(audio, chirp, mode='full')
    chirp_start = np.argmax(np.abs(correlation)) - len(chirp) + 1
    chirp_start = max(0, chirp_start)

    # Extract segment starting from chirp for IR analysis
    ir_samples = int(IR_ANALYSIS_MS * TARGET_SR / 1000)
    segment_start = chirp_start
    segment_end = min(len(audio), segment_start + len(chirp) + ir_samples)

    if segment_end - segment_start < len(chirp):
        # Chirp not found or too short, fallback to full audio
        segment = audio
    else:
        segment = audio[segment_start:segment_end]

    # Extract impulse response
    ir = extract_room_response(segment, chirp)

    # Find direct sound peak in IR
    direct_idx = np.argmax(np.abs(ir[:len(chirp)]))

    features = []

    # --- Early reflections (first 50ms after direct sound) ---
    early_samples = int(IR_EARLY_MS * TARGET_SR / 1000)
    early_start = direct_idx
    early_end = min(len(ir), direct_idx + early_samples)
    early_ir = ir[early_start:early_end]

    if len(early_ir) > 0:
        # Normalize to direct sound amplitude
        direct_amp = np.abs(ir[direct_idx]) + 1e-10
        early_normalized = np.abs(early_ir) / direct_amp

        # Peak positions (relative timing of early reflections)
        peaks_idx = np.where(early_normalized > 0.1)[0]
        if len(peaks_idx) > 1:
            peak_times = peaks_idx / TARGET_SR * 1000  # ms
            features.extend([
                np.mean(np.diff(peak_times)),  # average time between reflections
                np.std(np.diff(peak_times)) if len(peak_times) > 2 else 0,
                len(peaks_idx),  # number of significant reflections
            ])
        else:
            features.extend([0, 0, len(peaks_idx)])

        # Energy distribution in early reflections
        n_bins = 5
        bin_size = len(early_normalized) // n_bins
        for i in range(n_bins):
            bin_energy = np.sum(early_normalized[i*bin_size:(i+1)*bin_size]**2)
            features.append(np.log1p(bin_energy))

        # Peak amplitudes (relative to direct sound)
        sorted_peaks = np.sort(early_normalized)[::-1]
        features.extend(sorted_peaks[:min(5, len(sorted_peaks))].tolist())
        if len(sorted_peaks) < 5:
            features.extend([0] * (5 - len(sorted_peaks)))
    else:
        features.extend([0] * 13)  # 3 + 5 + 5 placeholder features

    # --- Reverb decay (RT60-like measure) ---
    late_start = direct_idx + early_samples
    late_end = min(len(ir), direct_idx + ir_samples)
    late_ir = ir[late_start:late_end] if late_end > late_start else np.zeros(100)

    if len(late_ir) > 10:
        # Compute energy decay curve (Schroeder integration)
        energy = late_ir ** 2
        decay_curve = np.cumsum(energy[::-1])[::-1]
        decay_curve = decay_curve / (decay_curve[0] + 1e-10)
        decay_db = 10 * np.log10(decay_curve + 1e-10)

        # Estimate decay rate (slope of dB curve)
        # Find -10dB and -30dB points for T10/T30
        t10_idx = np.searchsorted(-decay_db, 10)
        t30_idx = np.searchsorted(-decay_db, 30)

        if t30_idx > t10_idx and t30_idx < len(decay_db):
            decay_rate = (decay_db[t30_idx] - decay_db[t10_idx]) / (t30_idx - t10_idx)
        else:
            decay_rate = -0.1  # default slow decay

        features.append(decay_rate)

        # Decay curve shape samples
        sample_points = [0.1, 0.25, 0.5, 0.75, 0.9]
        for p in sample_points:
            idx = int(p * len(decay_db))
            features.append(decay_db[min(idx, len(decay_db)-1)])
    else:
        features.extend([0] * 6)

    # --- Frequency-dependent decay ---
    # Analyze how different frequency bands decay
    n_bands = 4
    band_edges = np.linspace(CHIRP_F0, CHIRP_F1, n_bands + 1)

    for i in range(n_bands):
        # Bandpass filter the IR
        low_freq = band_edges[i]
        high_freq = band_edges[i + 1]

        # Simple FFT-based bandpass
        ir_fft = np.fft.rfft(ir)
        freqs = np.fft.rfftfreq(len(ir), 1/TARGET_SR)
        mask = (freqs >= low_freq) & (freqs <= high_freq)
        ir_band_fft = ir_fft * mask
        ir_band = np.fft.irfft(ir_band_fft, n=len(ir))

        # Compute band energy decay
        band_energy = ir_band ** 2
        total_energy = np.sum(band_energy) + 1e-10

        # Early vs late energy ratio for this band
        early_band_energy = np.sum(band_energy[direct_idx:direct_idx+early_samples])
        late_band_energy = np.sum(band_energy[direct_idx+early_samples:direct_idx+ir_samples])

        features.append(np.log1p(early_band_energy / total_energy))
        features.append(np.log1p(late_band_energy / (early_band_energy + 1e-10)))

    return np.array(features, dtype=np.float32)


def extract_mfcc_features(audio: np.ndarray) -> np.ndarray:
    """Extract MFCC features and compute summary statistics.

    v3: Per-coefficient z-score normalization to remove device-specific biases.
    Focus on relative patterns within the recording, not absolute values.
    """
    mfccs = librosa.feature.mfcc(
        y=audio, sr=TARGET_SR, n_mfcc=N_MFCC, n_fft=N_FFT, hop_length=HOP_LENGTH
    )

    # Z-score normalize each coefficient independently
    # This removes device-specific level differences
    mfccs_normalized = np.zeros_like(mfccs)
    for i in range(N_MFCC):
        mean = np.mean(mfccs[i])
        std = np.std(mfccs[i])
        if std > 1e-6:
            mfccs_normalized[i] = (mfccs[i] - mean) / std
        else:
            mfccs_normalized[i] = mfccs[i] - mean

    stats = []
    # Skip MFCC[0] - even normalized, energy patterns vary by mic
    for i in range(1, N_MFCC):
        coef = mfccs_normalized[i]
        # Use relative/shape features, not absolute values
        stats.extend([
            np.percentile(coef, 10),
            np.percentile(coef, 25),
            np.percentile(coef, 50),
            np.percentile(coef, 75),
            np.percentile(coef, 90),
            # Shape: skewness and kurtosis-like measures
            np.mean(coef ** 3),  # skewness proxy
            np.mean(coef ** 4),  # kurtosis proxy
        ])

    # Delta MFCCs (also normalized)
    delta_mfccs = librosa.feature.delta(mfccs_normalized)
    for i in range(1, N_MFCC):
        coef = delta_mfccs[i]
        stats.extend([
            np.percentile(coef, 25),
            np.percentile(coef, 50),
            np.percentile(coef, 75),
            np.sign(np.mean(coef)),  # overall direction
        ])

    # Temporal pattern: zero-crossing rate of normalized coefficients
    for i in range(1, N_MFCC):
        coef = mfccs_normalized[i]
        zero_crossings = np.sum(np.diff(np.sign(coef)) != 0) / len(coef)
        stats.append(zero_crossings)

    return np.array(stats, dtype=np.float32)


def quantize_to_bits(features: np.ndarray, target_bits: int = None) -> np.ndarray:
    """Quantize feature vector to binary using median thresholding."""
    if target_bits is None:
        target_bits = get_target_bits()
    if len(features) >= target_bits:
        features = features[:target_bits]
    else:
        repetitions = (target_bits // len(features)) + 1
        features = np.tile(features, repetitions)[:target_bits]

    median = np.median(features)
    bits = (features > median).astype(np.uint8)
    return bits


def extract_bits(audio_data: bytes, chirp_seed: int = None) -> np.ndarray:
    """Full pipeline: audio bytes -> bit vector matching BCH codec length.

    If chirp_seed is provided, uses room acoustic features (primary method).
    Otherwise falls back to MFCC features.
    """
    audio = load_audio(audio_data)
    audio = normalize_duration(audio)
    audio = normalize_amplitude(audio)

    if chirp_seed is not None:
        features = extract_room_features(audio, chirp_seed)
    else:
        features = extract_mfcc_features(audio)

    bits = quantize_to_bits(features)
    return bits


def extract_room_bits(audio_data: bytes, chirp_seed: int) -> np.ndarray:
    """Extract bits using room acoustic features from chirp recording.

    Primary method for fuzzy commitment - captures room-specific acoustics.
    """
    return extract_bits(audio_data, chirp_seed=chirp_seed)


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """Convert bit array to bytes (MSB first, zero-padded to byte boundary)."""
    padded_len = ((len(bits) + 7) // 8) * 8
    padded = np.zeros(padded_len, dtype=np.uint8)
    padded[:len(bits)] = bits
    return np.packbits(padded).tobytes()


def bytes_to_bits(data: bytes, n_bits: int) -> np.ndarray:
    """Convert bytes back to bit array."""
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    return bits[:n_bits]


def hamming_distance(bits1: np.ndarray, bits2: np.ndarray) -> int:
    """Compute Hamming distance between two bit vectors."""
    return int(np.sum(bits1 != bits2))


def time_align(audio_a: np.ndarray, audio_b: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Align two audio signals using cross-correlation.

    Returns aligned versions and the lag in samples.
    """
    corr = np.correlate(audio_a, audio_b, mode='full')
    lag = np.argmax(corr) - len(audio_a) + 1

    if lag > 0:
        # B is ahead, shift B back (or A forward)
        audio_b = audio_b[lag:]
        audio_a = audio_a[:len(audio_b)]
    elif lag < 0:
        # A is ahead, shift A back
        audio_a = audio_a[-lag:]
        audio_b = audio_b[:len(audio_a)]

    # Ensure same length
    min_len = min(len(audio_a), len(audio_b))
    return audio_a[:min_len], audio_b[:min_len], lag


def extract_bits_aligned(audio_data_a: bytes, audio_data_b: bytes) -> tuple[np.ndarray, np.ndarray, int]:
    """Extract bits from two audio files with time alignment.

    Returns (bits_a, bits_b, lag_samples).
    """
    audio_a = load_audio(audio_data_a)
    audio_b = load_audio(audio_data_b)

    audio_a = normalize_amplitude(audio_a)
    audio_b = normalize_amplitude(audio_b)

    # Time align before normalization to target duration
    audio_a, audio_b, lag = time_align(audio_a, audio_b)

    # Now normalize to target duration
    audio_a = normalize_duration(audio_a)
    audio_b = normalize_duration(audio_b)

    features_a = extract_mfcc_features(audio_a)
    features_b = extract_mfcc_features(audio_b)

    bits_a = quantize_to_bits(features_a)
    bits_b = quantize_to_bits(features_b)

    return bits_a, bits_b, lag


def extract_bits_from_room(audio_data_a: bytes, audio_data_b: bytes, chirp_seed: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Extract bits using chirp-based alignment + MFCC features.

    v5c: Use chirp for precise time alignment, then extract MFCC from
    aligned audio segments. Combines precise timing with proven MFCC features.

    Returns (bits_a, bits_b, lag_samples).
    """
    audio_a = load_audio(audio_data_a)
    audio_b = load_audio(audio_data_b)

    audio_a = normalize_amplitude(audio_a)
    audio_b = normalize_amplitude(audio_b)

    # Generate the reference chirp for alignment
    chirp = generate_chirp(chirp_seed)
    chirp_samples = len(chirp)

    # Find chirp position in each recording via cross-correlation
    corr_a = np.correlate(audio_a, chirp, mode='full')
    corr_b = np.correlate(audio_b, chirp, mode='full')
    chirp_pos_a = np.argmax(np.abs(corr_a)) - chirp_samples + 1
    chirp_pos_b = np.argmax(np.abs(corr_b)) - chirp_samples + 1
    lag = chirp_pos_b - chirp_pos_a

    # Align audio based on chirp positions
    # Use the chirp position as the common reference point
    # Extract 2 seconds of audio starting from chirp
    segment_duration = int(2.0 * TARGET_SR)

    segment_a = audio_a[chirp_pos_a:chirp_pos_a + segment_duration]
    segment_b = audio_b[chirp_pos_b:chirp_pos_b + segment_duration]

    # Pad if needed
    if len(segment_a) < segment_duration:
        segment_a = np.pad(segment_a, (0, segment_duration - len(segment_a)))
    if len(segment_b) < segment_duration:
        segment_b = np.pad(segment_b, (0, segment_duration - len(segment_b)))

    # Trim to exact length
    segment_a = segment_a[:segment_duration]
    segment_b = segment_b[:segment_duration]

    # Extract MFCC features from aligned segments
    features_a = extract_mfcc_features(segment_a)
    features_b = extract_mfcc_features(segment_b)

    # Quantize to bits
    bits_a = quantize_to_bits(features_a)
    bits_b = quantize_to_bits(features_b)

    return bits_a, bits_b, lag
