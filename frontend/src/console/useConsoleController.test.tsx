import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { emptyRealtimeProjection } from './conversationProjection';
import { useConsoleController } from './useConsoleController';

const mocks = vi.hoisted(() => ({
  loadMessages: vi.fn(),
  legacy: {
    connected: false, inputLevel: 0, recordingElapsed: 0, speechFallbackAvailable: false,
    connect: vi.fn(), close: vi.fn(), startRecording: vi.fn(), stopRecording: vi.fn(),
    discardRecording: vi.fn(), cancelSpeech: vi.fn(), retrySpeech: vi.fn(), unlockSpeech: vi.fn(),
    handlePlaybackEvent: vi.fn(), client: vi.fn(() => null),
  },
  realtime: {
    state: 'disabled', stateDetail: undefined, compatibility: null, mediaState: 'idle', controlState: 'idle',
    projection: null as unknown, connected: false, muted: false, manualTurnTaking: false,
    connect: vi.fn(), close: vi.fn(), setMuted: vi.fn(), setManualTurnTaking: vi.fn(),
    startManualTurn: vi.fn(), stopManualTurn: vi.fn(), sendInput: vi.fn(), interruptSpeech: vi.fn(),
    resolveApproval: vi.fn(), submittingApprovalId: null, workerCommand: vi.fn(),
  },
}));

vi.mock('../lib/api', () => ({
  listSessions: vi.fn(async () => [
    { conversation_id: 'hvc_a', target: 'fake', title: 'A', created_at: 1, updated_at: 1 },
    { conversation_id: 'hvc_b', target: 'fake', title: 'B', created_at: 2, updated_at: 2 },
  ]),
  createSession: vi.fn(),
  loadSessionMessages: (...args: unknown[]) => mocks.loadMessages(...args),
}));
vi.mock('./useLegacyVoiceSession', () => ({ useLegacyVoiceSession: () => mocks.legacy }));
vi.mock('./useRealtimeSession', () => ({ useRealtimeSession: () => mocks.realtime }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}

describe('useConsoleController conversation identity', () => {
  beforeEach(() => {
    mocks.loadMessages.mockReset();
    mocks.realtime.projection = emptyRealtimeProjection;
  });

  it('suppresses loaded history on the same render that selects another conversation', async () => {
    const getToken = async () => null;
    const historyA = deferred<Array<{ role: 'user' | 'assistant'; content: string }>>();
    const historyB = deferred<Array<{ role: 'user' | 'assistant'; content: string }>>();
    mocks.loadMessages.mockImplementation((conversationId: string) => (
      conversationId === 'hvc_a' ? historyA.promise : historyB.promise
    ));
    const bootstrap = {
      server: { public_base_url: 'http://localhost:3000', auth_mode: 'development' as const },
      principal: { kind: 'development', owner_key: 'owner' },
      voice: { stt_provider: 'fake', tts_provider: 'fake', sample_rate: 16000, max_recording_seconds: 120, speak_replies_default: false },
      targets: [{ name: 'fake', label: 'Fake', preferred_transport: 'runs', api_key_configured: true, realtime_enabled: false }],
    };
    const { result } = renderHook(() => useConsoleController({
      authMode: 'development', getToken, bootstrap,
    }));
    await waitFor(() => expect(result.current.sessionKey).toBe('hvc_a'));
    await act(async () => { historyA.resolve([{ role: 'user', content: 'Conversation A' }]); await historyA.promise; });
    await waitFor(() => expect(result.current.messages).toEqual([{ role: 'user', content: 'Conversation A' }]));

    act(() => result.current.selectSession('hvc_b'));
    expect(result.current.sessionKey).toBe('hvc_b');
    expect(result.current.messages).toEqual([]);

    await act(async () => { historyB.resolve([{ role: 'assistant', content: 'Conversation B' }]); await historyB.promise; });
    await waitFor(() => expect(result.current.messages).toEqual([{ role: 'assistant', content: 'Conversation B' }]));
  });
});
