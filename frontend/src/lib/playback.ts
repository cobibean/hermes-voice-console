export interface PlaybackAdapter {
  play(data: Uint8Array, mime: string, signal: AbortSignal): Promise<void>;
  unlock?(): Promise<void>;
  stop?(): void;
}

export class BrowserPlaybackAdapter implements PlaybackAdapter {
  private audio: HTMLAudioElement | null = null;

  async unlock(): Promise<void> {
    const audio = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=');
    audio.muted = true;
    try {
      await audio.play();
      audio.pause();
    } catch {
      // Some browsers still defer playback. The real clip retries after the next gesture.
    }
  }

  async play(data: Uint8Array, mime: string, signal: AbortSignal): Promise<void> {
    const audioBytes = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
    const blob = new Blob([audioBytes], { type: mime });
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
        audio.addEventListener('error', () => { cleanup(); reject(new Error('Audio playback failed; the text answer is still available')); }, { once: true });
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

interface IncomingClip {
  turnId: string;
  chunkIndex: number;
  mime: string;
  bytes: Uint8Array[];
}

export class PlaybackQueue {
  private generation = 0;
  private activeTurn: string | null = null;
  private incoming: IncomingClip | null = null;
  private lastChunkByTurn = new Map<string, number>();
  private chain: Promise<void> = Promise.resolve();
  private controller: AbortController | null = null;
  private failedClip: { data: Uint8Array; mime: string; turnId: string } | null = null;

  constructor(
    private adapter: PlaybackAdapter = new BrowserPlaybackAdapter(),
    private onError?: (message: string) => void,
    private onFallbackChange?: (available: boolean) => void,
  ) {}

  get activeTurnId(): string | null { return this.activeTurn; }

  unlock(): Promise<void> { return this.adapter.unlock?.() ?? Promise.resolve(); }

  start(turnId: string, chunkIndex: number, mime: string): void {
    const last = this.lastChunkByTurn.get(turnId) ?? -1;
    if (chunkIndex <= last || (this.activeTurn && this.activeTurn !== turnId)) return;
    this.activeTurn = turnId;
    this.incoming = { turnId, chunkIndex, mime, bytes: [] };
  }

  pushChunk(chunk: ArrayBuffer): void {
    this.incoming?.bytes.push(new Uint8Array(chunk));
  }

  end(turnId: string, chunkIndex: number): void {
    const incoming = this.incoming;
    if (!incoming || incoming.turnId !== turnId || incoming.chunkIndex !== chunkIndex) return;
    this.incoming = null;
    this.lastChunkByTurn.set(turnId, chunkIndex);
    const generation = this.generation;
    const clip = merge(incoming.bytes);
    if (clip.byteLength === 0) return;
    this.chain = this.chain
      .catch(() => undefined)
      .then(async () => {
        if (generation !== this.generation || this.activeTurn !== turnId) return;
        this.controller = new AbortController();
        try {
          await this.adapter.play(clip, incoming.mime, this.controller.signal);
        } catch (err) {
          if ((err as DOMException).name !== 'AbortError') {
            this.failedClip = { data: clip, mime: incoming.mime, turnId };
            this.onFallbackChange?.(true);
            this.onError?.('Browser blocked automatic speech. Use Play spoken reply to retry; the text answer is complete.');
          }
        } finally {
          if (generation === this.generation) this.controller = null;
        }
      });
  }

  complete(turnId: string): void {
    if (this.activeTurn !== turnId) return;
    const generation = this.generation;
    void this.chain.finally(() => {
      if (generation === this.generation && this.activeTurn === turnId) this.activeTurn = null;
    });
  }

  async retry(): Promise<void> {
    const clip = this.failedClip;
    if (!clip) return;
    await this.unlock();
    const controller = new AbortController();
    this.controller = controller;
    try {
      await this.adapter.play(clip.data, clip.mime, controller.signal);
      this.failedClip = null;
      this.onFallbackChange?.(false);
    } catch (err) {
      if ((err as DOMException).name !== 'AbortError') this.onError?.('Speech playback is still blocked; the text answer remains available.');
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  cancel(turnId?: string): void {
    if (turnId && this.activeTurn && turnId !== this.activeTurn) return;
    this.activeTurn = null;
    this.incoming = null;
    this.failedClip = null;
    this.onFallbackChange?.(false);
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
