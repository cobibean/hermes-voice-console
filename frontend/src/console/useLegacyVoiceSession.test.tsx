import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useLegacyVoiceSession } from './useLegacyVoiceSession';

const mocks = vi.hoisted(() => ({
  clients: [] as Array<{ isOpen: boolean; connect: ReturnType<typeof vi.fn>; startRecording: ReturnType<typeof vi.fn>; stopRecording: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn>; sendAudio: ReturnType<typeof vi.fn> }>,
  captureStop: vi.fn(async () => undefined),
}));

vi.mock('../lib/voiceClient', () => ({
  VoiceClient: class {
    isOpen = false;
    connect = vi.fn(async () => { this.isOpen = true; });
    startRecording = vi.fn(async () => undefined);
    stopRecording = vi.fn();
    cancelRecording = vi.fn();
    cancelTts = vi.fn();
    sendAudio = vi.fn();
    close = vi.fn(() => { this.isOpen = false; });
    constructor() { mocks.clients.push(this); }
  },
}));
vi.mock('../lib/capture', () => ({
  startPcm16Capture: vi.fn(async () => ({ stop: mocks.captureStop })),
}));
vi.mock('../lib/playback', () => ({
  PlaybackQueue: class {
    activeTurnId: string | null = null;
    unlock = vi.fn(async () => undefined);
    retry = vi.fn(async () => undefined);
    cancel = vi.fn();
    pushChunk = vi.fn();
    start = vi.fn();
    end = vi.fn();
    complete = vi.fn();
  },
}));

describe('useLegacyVoiceSession', () => {
  beforeEach(() => { mocks.clients.length = 0; mocks.captureStop.mockClear(); });

  it('preserves one legacy client/capture and tears both down deterministically', async () => {
    const { result, unmount } = renderHook(() => useLegacyVoiceSession({
      enabled: true, authMode: 'development', getToken: async () => null,
      target: 'fake', conversationId: 'hvc_1', speakReplies: false,
      onEvent: vi.fn(), onError: vi.fn(),
    }));
    await act(async () => { await Promise.all([result.current.connect(), result.current.connect()]); });
    expect(mocks.clients).toHaveLength(1);
    await act(async () => { await result.current.startRecording('turn_1'); });
    act(() => result.current.stopRecording('turn_1'));
    await act(async () => { await Promise.resolve(); });
    expect(mocks.captureStop).toHaveBeenCalledOnce();
    expect(mocks.clients[0].stopRecording).toHaveBeenCalledWith('turn_1');
    unmount();
    expect(mocks.clients[0].close).toHaveBeenCalled();
  });
});
