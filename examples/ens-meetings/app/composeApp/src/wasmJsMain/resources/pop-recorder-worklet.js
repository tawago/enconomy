/* PoP mic recorder (adapted from research/sound-bound/static/recorder-worklet.js).
 * Posts every input block with its context frame so the main thread can key the ring buffer by frame and
 * spot dropped audio. Output stays silent: the mic never reaches the speaker.
 */
class PopRecorder extends AudioWorkletProcessor {
  process(inputs, outputs) {
    for (const channels of outputs) for (const ch of channels) ch.fill(0);
    const input = inputs[0] || [];
    const ch = input[0];
    if (!ch) return true; // no input this quantum: the gap shows up as a frame jump
    const samples = new Float32Array(ch.length);
    samples.set(ch);
    this.port.postMessage({ type: 'block', frame: currentFrame, samples }, [samples.buffer]);
    return true;
  }
}

registerProcessor('pop-recorder', PopRecorder);
