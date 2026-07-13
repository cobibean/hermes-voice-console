import { voiceDiagnostic } from './diagnostics';

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
    audio: {
      channelCount: { ideal: 1 },
      sampleRate: { ideal: 48_000 },
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule('/voice/pcm-worklet.js');
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'pcm16-downsampler');
  const track = stream.getAudioTracks()[0];
  voiceDiagnostic('capture.started', {
    audioContextRate: ctx.sampleRate,
    trackRate: track?.getSettings().sampleRate,
    channelCount: track?.getSettings().channelCount,
  });
  let stopped = false;
  let chunks = 0;
  let pcmBytes = 0;
  node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
    if (stopped) return;
    chunks += 1;
    pcmBytes += event.data.byteLength;
    if (chunks % 25 === 0) voiceDiagnostic('capture.progress', { chunks, pcmBytes }, true);
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
      if (stopped) return;
      stopped = true;
      node.port.onmessage = null;
      try { node.port.close(); } catch { /* noop */ }
      try { source.disconnect(); } catch { /* noop */ }
      try { node.disconnect(); } catch { /* noop */ }
      stream.getTracks().forEach((track) => track.stop());
      await ctx.close().catch(() => undefined);
      voiceDiagnostic('capture.stopped', { chunks, pcmBytes });
    },
  };
}
