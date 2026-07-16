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
    projection: null as unknown, connected: false, muted: false, manualTurnTaking: false, manualControlsAvailable: false,
    manualCaptureState: 'idle', manualCaptureError: undefined,
    connect: vi.fn(), close: vi.fn(), setMuted: vi.fn(), setManualTurnTaking: vi.fn(),
    startManualTurn: vi.fn(), stopManualTurn: vi.fn(), discardManualTurn: vi.fn(), commitManualTurn: vi.fn(), sendInput: vi.fn(), interruptSpeech: vi.fn(),
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
vi.mock('./useRealtimeSession', () => ({ useRealtimeSession: () => ({ ...mocks.realtime }) }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}
const getToken = async () => null;

describe('useConsoleController conversation identity', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.loadMessages.mockReset();
    mocks.realtime.projection = emptyRealtimeProjection;
    mocks.realtime.state = 'disabled';
    mocks.realtime.mediaState = 'idle';
    mocks.realtime.controlState = 'idle';
    mocks.realtime.connected = false;
    mocks.realtime.manualControlsAvailable = false;
    mocks.realtime.manualTurnTaking = false;
    mocks.realtime.manualCaptureState = 'idle';
    mocks.realtime.manualCaptureError = undefined;
    mocks.realtime.setManualTurnTaking.mockResolvedValue(undefined);
    mocks.realtime.commitManualTurn.mockResolvedValue(undefined);
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

  it('wires server-authoritative manual toggle and click-send only while ready and supported', async () => {
    mocks.loadMessages.mockResolvedValue([]);
    mocks.realtime.state = 'ready';
    mocks.realtime.mediaState = 'connected';
    mocks.realtime.controlState = 'ready';
    mocks.realtime.connected = true;
    mocks.realtime.manualControlsAvailable = true;
    mocks.realtime.manualTurnTaking = true;
    mocks.realtime.manualCaptureState = 'capturing';
    const bootstrap = {
      server: { public_base_url: 'http://localhost:3000', auth_mode: 'development' as const },
      principal: { kind: 'development', owner_key: 'owner' },
      voice: { stt_provider: 'fake', tts_provider: 'fake', sample_rate: 16000, max_recording_seconds: 120, speak_replies_default: false },
      targets: [{ name: 'fake', label: 'Fake', preferred_transport: 'runs', api_key_configured: true, realtime_enabled: true }],
    };
    const { result, rerender } = renderHook(() => useConsoleController({
      authMode: 'development', getToken, bootstrap,
    }));
    await waitFor(() => expect(result.current.sessionKey).toBe('hvc_a'));
    expect(result.current.realtime.onToggleManualTurnTaking).toBeDefined();
    expect(result.current.realtime.onStartManualTurn).toBeUndefined();
    expect(result.current.realtime.onSendManualTurn).toBeDefined();
    expect(result.current.realtime.onDiscardManualTurn).toBeDefined();

    act(() => result.current.realtime.onToggleManualTurnTaking?.());
    expect(mocks.realtime.setManualTurnTaking).toHaveBeenCalledWith(false);
    act(() => result.current.realtime.onSendManualTurn?.());
    expect(mocks.realtime.stopManualTurn).toHaveBeenCalledOnce();
    expect(mocks.realtime.commitManualTurn).toHaveBeenCalledOnce();
    act(() => result.current.realtime.onDiscardManualTurn?.());
    expect(mocks.realtime.discardManualTurn).toHaveBeenCalledOnce();

    mocks.realtime.manualCaptureState = 'idle';
    rerender();
    expect(result.current.realtime.onStartManualTurn).toBeDefined();
    expect(result.current.realtime.onSendManualTurn).toBeUndefined();
    act(() => result.current.realtime.onStartManualTurn?.());
    expect(mocks.realtime.startManualTurn).toHaveBeenCalledOnce();
    act(() => result.current.realtime.onUseLegacy?.());
    expect(mocks.realtime.close).toHaveBeenCalledOnce();
    expect(result.current.transport).toBe('legacy');
  });
});
