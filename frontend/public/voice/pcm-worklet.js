const TARGET_RATE = 16000;

class PCM16DownsamplerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / TARGET_RATE;
    this._position = 0;
    this._leftover = new Float32Array(0);
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel?.length) return true;

    const data = new Float32Array(this._leftover.length + channel.length);
    data.set(this._leftover);
    data.set(channel, this._leftover.length);
    const output = [];

    // Average every source-rate window instead of point-sampling. This acts as
    // a small anti-alias filter and is materially cleaner on mobile 44.1/48kHz mics.
    while (this._position + this._ratio <= data.length) {
      const start = Math.floor(this._position);
      const end = Math.min(data.length, Math.ceil(this._position + this._ratio));
      let sum = 0;
      for (let index = start; index < end; index += 1) sum += data[index];
      const sample = sum / Math.max(1, end - start);
      const clamped = Math.max(-1, Math.min(1, sample));
      output.push(Math.round(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff));
      this._position += this._ratio;
    }

    const consumed = Math.floor(this._position);
    this._leftover = data.slice(consumed);
    this._position -= consumed;
    if (output.length) {
      const pcm = new Int16Array(output);
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor('pcm16-downsampler', PCM16DownsamplerProcessor);
