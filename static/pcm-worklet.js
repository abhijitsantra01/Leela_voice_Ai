// AudioWorklet runs away from the UI thread. Browser capture is requested at 16 kHz.
class PCMProcessor extends AudioWorkletProcessor {
  constructor() { super(); this.pending = new Int16Array(1600); this.offset = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    let energy = 0;
    for (let i = 0; i < input.length; i++) {
      const sample = Math.max(-1, Math.min(1, input[i]));
      energy += sample * sample;
      this.pending[this.offset++] = sample < 0 ? sample * 32768 : sample * 32767;
      if (this.offset === this.pending.length) {
        const data = this.pending.buffer;
        this.port.postMessage({audio: data}, [data]);
        this.pending = new Int16Array(1600); this.offset = 0;
      }
    }
    this.port.postMessage({level: Math.sqrt(energy / input.length)});
    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
