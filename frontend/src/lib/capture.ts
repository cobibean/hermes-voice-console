export interface CaptureSession {
  stop(): Promise<void>;
}

export function browserSupportsCapture(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    typeof window !== 'undefined' &&
    'AudioContext' in window &&
    'AudioWorkletNode' in window
  );
}

export async function startPcm16Capture(
  onChunk: (chunk: ArrayBuffer) => void,
  onLevel?: (level: number) => void,
): Promise<CaptureSession> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule('/voice/pcm-worklet.js');
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'pcm16-downsampler');
  node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
    const pcm = new Int16Array(event.data);
    let sum = 0;
    for (const sample of pcm) sum += (sample / 32768) ** 2;
    onLevel?.(Math.min(1, Math.sqrt(sum / Math.max(1, pcm.length)) * 5));
    onChunk(event.data);
  };
  source.connect(node);
  const sink = ctx.createGain();
  sink.gain.value = 0;
  node.connect(sink);
  sink.connect(ctx.destination);
  return {
    async stop() {
      try { node.port.close(); } catch { /* noop */ }
      try { node.disconnect(); } catch { /* noop */ }
      stream.getTracks().forEach((track) => track.stop());
      await ctx.close().catch(() => undefined);
    },
  };
}
