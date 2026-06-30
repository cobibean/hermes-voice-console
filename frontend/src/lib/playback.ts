export interface PlaybackAdapter {
  play(data: Uint8Array, signal: AbortSignal): Promise<void>;
  stop?(): void;
}

export class BrowserPlaybackAdapter implements PlaybackAdapter {
  private audio: HTMLAudioElement | null = null;

  async play(data: Uint8Array, signal: AbortSignal): Promise<void> {
    const audioBytes = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
    const blob = new Blob([audioBytes]);
    const url = URL.createObjectURL(blob);
    try {
      await new Promise<void>((resolve, reject) => {
        const audio = new Audio(url);
        this.audio = audio;
        const cleanup = () => {
          if (this.audio === audio) this.audio = null;
          signal.removeEventListener('abort', onAbort);
        };
        const onAbort = () => {
          audio.pause();
          audio.currentTime = 0;
          cleanup();
          reject(new DOMException('Playback cancelled', 'AbortError'));
        };
        signal.addEventListener('abort', onAbort, { once: true });
        audio.addEventListener('ended', () => { cleanup(); resolve(); }, { once: true });
        audio.addEventListener('error', () => { cleanup(); reject(new Error('Audio playback failed')); }, { once: true });
        void audio.play().catch((err) => { cleanup(); reject(err); });
      });
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  stop(): void {
    if (this.audio) {
      this.audio.pause();
      this.audio.currentTime = 0;
      this.audio = null;
    }
  }
}

export class PlaybackQueue {
  private adapter: PlaybackAdapter;
  private generation = 0;
  private activeTurn: string | null = null;
  private incoming: Uint8Array[] = [];
  private chain: Promise<void> = Promise.resolve();
  private controller: AbortController | null = null;

  constructor(adapter: PlaybackAdapter = new BrowserPlaybackAdapter()) {
    this.adapter = adapter;
  }

  get activeTurnId(): string | null {
    return this.activeTurn;
  }

  start(turnId: string): void {
    this.activeTurn = turnId;
    this.incoming = [];
  }

  pushChunk(chunk: ArrayBuffer): void {
    if (!this.activeTurn) return;
    this.incoming.push(new Uint8Array(chunk));
  }

  end(turnId: string): void {
    if (turnId !== this.activeTurn) return;
    const generation = this.generation;
    const clip = merge(this.incoming);
    this.incoming = [];
    this.activeTurn = null;
    if (clip.byteLength === 0) return;
    this.chain = this.chain
      .catch(() => undefined)
      .then(async () => {
        if (generation !== this.generation) return;
        this.controller = new AbortController();
        try {
          await this.adapter.play(clip, this.controller.signal);
        } catch (err) {
          if ((err as DOMException).name !== 'AbortError') throw err;
        } finally {
          if (generation === this.generation) this.controller = null;
        }
      });
  }

  cancel(turnId?: string): void {
    if (!turnId || turnId === this.activeTurn) {
      this.activeTurn = null;
      this.incoming = [];
    }
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
    this.adapter.stop?.();
  }
}

function merge(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return merged;
}
