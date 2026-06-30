const TARGET_RATE = 16000;

class PCM16DownsamplerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / TARGET_RATE;
    this._carry = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel || channel.length === 0) return true;
    const out = [];
    let pos = this._carry;
    while (pos < channel.length) {
      const i = Math.floor(pos);
      const frac = pos - i;
      const a = channel[i];
      const b = i + 1 < channel.length ? channel[i + 1] : channel[i];
      const sample = a + (b - a) * frac;
      const clamped = Math.max(-1, Math.min(1, sample));
      out.push(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
      pos += this._ratio;
    }
    this._carry = pos - channel.length;
    if (out.length > 0) {
      const buf = new Int16Array(out);
      this.port.postMessage(buf.buffer, [buf.buffer]);
    }
    return true;
  }
}

registerProcessor('pcm16-downsampler', PCM16DownsamplerProcessor);
