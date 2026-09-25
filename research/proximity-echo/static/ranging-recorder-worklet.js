/* The input microphone is recorded even while this device's probes play.
 * Outputs remain silent: the microphone is never sent to the loudspeaker.
 */
class RangingRecorderProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        const settings = options.processorOptions || {};
        this.startFrame = settings.startFrame;
        this.endFrame = settings.endFrame;
        if (!Number.isSafeInteger(this.startFrame) || !Number.isSafeInteger(this.endFrame)
                || this.endFrame <= this.startFrame) {
            throw new Error('Invalid recorder frame interval');
        }
        this.batchFrames = 2048;
        this.pending = [];
        this.blocks = [];
        this.pendingFrames = 0;
        this.frameCount = 0;
        this.blockIndex = 0;
        this.expectedContextFrame = this.startFrame;
        this.stopped = false;
        this.port.onmessage = ({ data }) => {
            if (data?.type === 'stop' && !this.stopped) {
                this.finish('stopped');
            }
        };
    }

    flush() {
        if (!this.pendingFrames) return;
        const samples = new Float32Array(this.pendingFrames);
        let offset = 0;
        for (const part of this.pending) {
            samples.set(part, offset);
            offset += part.length;
        }
        this.port.postMessage({ type: 'samples', samples, blocks: this.blocks }, [samples.buffer]);
        this.pending = [];
        this.blocks = [];
        this.pendingFrames = 0;
    }

    finish(type) {
        this.flush();
        this.stopped = true;
        this.port.postMessage({ type, frame_count: this.frameCount, end_context_frame: this.expectedContextFrame });
    }

    process(inputs, outputs) {
        for (const channels of outputs) {
            for (const channel of channels) channel.fill(0);
        }
        if (this.stopped) return false;
        const input = inputs[0] || [];
        const quantumFrames = outputs[0]?.[0]?.length || input[0]?.length || 128;
        const first = Math.max(currentFrame, this.startFrame);
        const last = Math.min(currentFrame + quantumFrames, this.endFrame);
        if (last > first) {
            const count = last - first;
            const samples = new Float32Array(count);
            const channel = input[0];
            if (channel) samples.set(channel.subarray(first - currentFrame, last - currentFrame));
            let peak = 0;
            let clipped = 0;
            let nonfinite = 0;
            for (const value of samples) {
                if (!Number.isFinite(value)) {
                    nonfinite += 1;
                } else {
                    const absolute = Math.abs(value);
                    peak = Math.max(peak, absolute);
                    if (absolute >= 0.999) clipped += 1;
                }
            }
            this.blocks.push({
                index: this.blockIndex++,
                start_frame: this.frameCount,
                frame_count: count,
                context_frame: first,
                context_time: first / sampleRate,
                context_gap_frames: first - this.expectedContextFrame,
                input_channels: input.length,
                missing_input_frames: channel ? 0 : count,
                peak,
                clipped_samples: clipped,
                nonfinite_samples: nonfinite,
            });
            this.pending.push(samples);
            this.pendingFrames += count;
            this.frameCount += count;
            this.expectedContextFrame = last;
            if (this.pendingFrames >= this.batchFrames) this.flush();
        }
        if (currentFrame + quantumFrames >= this.endFrame) {
            this.finish('complete');
            return false;
        }
        return true;
    }
}

registerProcessor('ranging-recorder', RangingRecorderProcessor);
