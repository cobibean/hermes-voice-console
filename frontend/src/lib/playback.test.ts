import { describe, expect, it, vi } from 'vitest';
import { PlaybackQueue, type PlaybackAdapter } from './playback';

class FakeAdapter implements PlaybackAdapter {
  played: number[] = [];
  stopped = 0;
  async play(data: Uint8Array, signal: AbortSignal): Promise<void> {
    if (signal.aborted) return;
    this.played.push(data.byteLength);
  }
  stop(): void { this.stopped += 1; }
}

describe('PlaybackQueue', () => {
  it('plays clips sequentially after tts.end', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('t1');
    queue.pushChunk(new Uint8Array([1, 2]).buffer);
    queue.pushChunk(new Uint8Array([3]).buffer);
    queue.end('t1');
    await vi.waitFor(() => expect(adapter.played).toEqual([3]));
  });

  it('drops stale generation after cancel', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('old');
    queue.pushChunk(new Uint8Array([1, 2, 3]).buffer);
    queue.cancel('old');
    queue.end('old');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(adapter.played).toEqual([]);
    expect(adapter.stopped).toBe(1);
  });

  it('ignores tts.end for a stale turn id', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('current');
    queue.pushChunk(new Uint8Array([1, 2, 3]).buffer);
    queue.end('old');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(adapter.played).toEqual([]);
  });
});
