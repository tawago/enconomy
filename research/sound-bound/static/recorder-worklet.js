/* sound-bound recorder.
 * Keeps recording while this device plays its own probe. Output stays silent:
 * the microphone is never routed back to the speaker.
 * Every block carries its currentFrame so the main thread can spot dropped audio.
 */
class SoundBoundRecorder extends AudioWorkletProcessor {
    constructor() {
        super();
        this.stopped = false;
        this.port.onmessage = ({ data }) => {
            if (data && data.type === 'stop') {
                this.stopped = true;
                this.port.postMessage({ type: 'stopped' });
            }
        };
    }

    process(inputs, outputs) {
        for (const channels of outputs) {
            for (const channel of channels) channel.fill(0);
        }
        if (this.stopped) return false;

        const input = inputs[0] || [];
        const channel = input[0];
        const frames = channel ? channel.length : (outputs[0] && outputs[0][0] ? outputs[0][0].length : 128);
        const samples = new Float32Array(frames);
        if (channel) samples.set(channel);

        this.port.postMessage({
            type: 'block',
            samples,
            contextFrame: currentFrame,
            frames,
            hasInput: Boolean(channel),
        }, [samples.buffer]);
        return true;
    }
}

registerProcessor('sound-bound-recorder', SoundBoundRecorder);
