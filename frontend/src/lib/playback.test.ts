import { describe, expect, it, vi } from 'vitest';
import { PlaybackQueue, type PlaybackAdapter } from './playback';

class FakeAdapter implements PlaybackAdapter {
  played: Array<[number, string]> = [];
  stopped = 0;
  async play(data: Uint8Array, mime: string, signal: AbortSignal): Promise<void> {
    if (signal.aborted) return;
    this.played.push([data.byteLength, mime]);
  }
  stop(): void { this.stopped += 1; }
}

class BlockedAdapter extends FakeAdapter {
  blocked = true;
  override async play(data: Uint8Array, mime: string, signal: AbortSignal): Promise<void> {
    if (this.blocked) throw new DOMException('blocked', 'NotAllowedError');
    await super.play(data, mime, signal);
  }
}

describe('PlaybackQueue', () => {
  it('plays clips sequentially after tts.end', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('t1', 0, 'audio/mpeg');
    queue.pushChunk(new Uint8Array([1, 2]).buffer);
    queue.pushChunk(new Uint8Array([3]).buffer);
    queue.end('t1', 0);
    await vi.waitFor(() => expect(adapter.played).toEqual([[3, 'audio/mpeg']]));
  });

  it('drops stale generation after cancel', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('old', 0, 'audio/wav');
    queue.pushChunk(new Uint8Array([1, 2, 3]).buffer);
    queue.cancel('old');
    queue.end('old', 0);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(adapter.played).toEqual([]);
    expect(adapter.stopped).toBe(1);
  });

  it('ignores tts.end for a stale turn id', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('current', 0, 'audio/wav');
    queue.pushChunk(new Uint8Array([1, 2, 3]).buffer);
    queue.end('old', 0);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(adapter.played).toEqual([]);
  });

  it('rejects replayed and stale chunk indexes', async () => {
    const adapter = new FakeAdapter();
    const queue = new PlaybackQueue(adapter);
    queue.start('t1', 0, 'audio/wav');
    queue.pushChunk(new Uint8Array([1]).buffer);
    queue.end('t1', 0);
    queue.start('t1', 0, 'audio/wav');
    queue.pushChunk(new Uint8Array([2, 3]).buffer);
    queue.end('t1', 0);
    await vi.waitFor(() => expect(adapter.played).toEqual([[1, 'audio/wav']]));
  });

  it('offers a user-gesture retry when autoplay is blocked', async () => {
    const adapter = new BlockedAdapter();
    const fallback = vi.fn();
    const queue = new PlaybackQueue(adapter, undefined, fallback);
    queue.start('t1', 0, 'audio/mpeg');
    queue.pushChunk(new Uint8Array([1, 2]).buffer);
    queue.end('t1', 0);
    await vi.waitFor(() => expect(fallback).toHaveBeenCalledWith(true));
    adapter.blocked = false;
    await queue.retry();
    expect(adapter.played).toEqual([[2, 'audio/mpeg']]);
    expect(fallback).toHaveBeenLastCalledWith(false);
  });
});
