package com.enconomy.pop

/**
 * TODO(audio lane): AVAudioEngine, §4.2-§4.4 on iOS (decision note §4). AVAudioSession
 * .playAndRecord, mode .measurement, .defaultToSpeaker, 48 kHz preferred, voice processing off;
 * interruption aborts the run; play/rec timestamps from AVAudioTime.hostTime (see monoNanos).
 */
actual fun createAudioEngine(): AudioEngine = IosAudioEngine()

class IosAudioEngine : AudioEngine {
    override fun preflight(): AudioPreflight = AudioPreflight(
        sampleRate = 48_000, volume = 0, volumeMax = 0, externalOutput = null,
        micPermission = hasMicPermission(), unprocessed = false, outputLatencyMs = null,
        problems = listOf("iOS audio engine not implemented yet"), warnings = emptyList(),
    )

    override fun setMediaVolume(frac: Double) {}

    override fun prepare(sr: Int, play: FloatArray) {
        throw AudioException("capture_failed", "iOS audio engine not implemented")
    }

    override suspend fun run(plan: RunPlan): Capture =
        throw AudioException("capture_failed", "iOS audio engine not implemented")

    override fun release() {}
}
