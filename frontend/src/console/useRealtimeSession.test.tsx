import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { supportsManualTurnControls, useRealtimeSession } from './useRealtimeSession';

const mocks = vi.hoisted(() => ({
  approval: vi.fn(),
  manualCommit: vi.fn(),
  turnMode: vi.fn(),
  media: [] as Array<{ setMuted: ReturnType<typeof vi.fn> }>,
  controls: [] as Array<{ options: Record<string, any>; isReady: boolean }>,
}));

vi.mock('../lib/api', () => ({
  loadRealtimeCompatibility: vi.fn(async () => ({
    compatible: true, version: '1.0', reasons: [],
    contract: { sessions: { manual_audio_commit: true, turn_mode_update: true, turn_modes: ['server_vad', 'manual'] } },
  })),
  createRealtimeSession: vi.fn(), activateRealtimeSession: vi.fn(), closeRealtimeSession: vi.fn(async () => undefined),
}));
vi.mock('../lib/realtimeClient', () => ({
  RealtimeClient: class {
    activeSession = {
      contract_version: '1.0', realtime_session_id: 'rt_1', conversation_id: 'hvc_1',
      session_generation: 1, state: 'active', answer_sdp: 'v=0', client_request_id: 'create_1',
    };
    isConnected = true;
    setMuted = vi.fn();
    constructor(private options: { onState?: (state: string) => void }) { mocks.media.push(this); }
    async connect() { this.options.onState?.('connected'); return this.activeSession; }
    close() { return this.activeSession; }
  },
}));
vi.mock('../lib/realtimeControlClient', () => ({
  RealtimeControlClient: class {
    isReady = false;
    constructor(public options: Record<string, any>) { mocks.controls.push(this); }
    async connect() {
      this.options.onSnapshot({
        conversation_id: this.options.conversationId, last_event_id: 'rte_1',
        worker_jobs: [{ worker_job_id: 'job_old', status: 'running', revision: 1 }],
        tool_calls: [{ tool_call_id: 'call_1', tool_name: 'terminal' }],
        pending_approvals: [{ approval_id: 'approval_1', tool_call_id: 'call_1', state: 'pending', choices: ['once', 'deny'] }],
      });
      this.isReady = true;
      this.options.onState?.('ready');
    }
    close() { this.isReady = false; }
    approval(...args: unknown[]) { return mocks.approval(...args); }
    manualAudioCommit(...args: unknown[]) { return mocks.manualCommit(...args); }
    turnModeUpdate(...args: unknown[]) { return mocks.turnMode(...args); }
    input = vi.fn(async () => ({ accepted: true }));
    interrupt = vi.fn(async () => ({ interrupted: true }));
    workerCommand = vi.fn(async () => ({ acknowledgement: 'applied', revision: 2 }));
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const getToken = async () => null;

describe('useRealtimeSession approval and identity ownership', () => {
  beforeEach(() => {
    mocks.approval.mockReset();
    mocks.manualCommit.mockReset();
    mocks.turnMode.mockReset();
    mocks.controls.length = 0;
    mocks.media.length = 0;
  });

  it('requires every advertised manual-turn contract key', () => {
    expect(supportsManualTurnControls({
      compatible: true, version: '1.0', reasons: [],
      contract: { sessions: { manual_audio_commit: true, turn_mode_update: true, turn_modes: ['server_vad', 'manual'] } },
    })).toBe(true);
    expect(supportsManualTurnControls({
      compatible: true, version: '1.0', reasons: [],
      contract: { sessions: { manual_audio_commit: true, turn_modes: ['server_vad', 'manual'] } },
    })).toBe(false);
  });

  it('latches one approval submission until error or authoritative final state', async () => {
    const getToken = async () => null;
    const firstAck = deferred<Record<string, unknown>>();
    mocks.approval.mockReturnValueOnce(firstAck.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));

    let first!: Promise<void>;
    let duplicate!: Promise<void>;
    act(() => {
      first = result.current.resolveApproval('approval_1', 'once');
      duplicate = result.current.resolveApproval('approval_1', 'once');
    });
    expect(first).toBe(duplicate);
    expect(mocks.approval).toHaveBeenCalledTimes(1);
    expect(result.current.submittingApprovalId).toBe('approval_1');

    firstAck.reject(new Error('control reconnect'));
    await expect(first).rejects.toThrow('control reconnect');
    await waitFor(() => expect(result.current.submittingApprovalId).toBeNull());

    const secondAck = deferred<Record<string, unknown>>();
    mocks.approval.mockReturnValueOnce(secondAck.promise);
    let accepted!: Promise<void>;
    act(() => { accepted = result.current.resolveApproval('approval_1', 'deny'); });
    secondAck.resolve({ accepted: true });
    await accepted;
    expect(result.current.submittingApprovalId).toBe('approval_1');
    act(() => mocks.controls.at(-1)!.options.onEvent({
      event_id: 'rte_2', type: 'approval.resolved', conversation_id: 'hvc_1',
      payload: { approval_id: 'approval_1' },
    }));
    await waitFor(() => expect(result.current.submittingApprovalId).toBeNull());
  });

  it('waits for the authoritative mode ack and keeps manual capture muted until recording starts', async () => {
    const ack = deferred<Record<string, unknown>>();
    mocks.turnMode.mockReturnValueOnce(ack.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(result.current.manualControlsAvailable).toBe(true);

    let change!: Promise<void>;
    act(() => { change = result.current.setManualTurnTaking(true); });
    expect(result.current.manualTurnTaking).toBe(false);
    expect(mocks.turnMode).toHaveBeenCalledWith(expect.stringMatching(/^turn-mode-/), 1, 'manual');
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);

    ack.resolve({ state: 'accepted', turn_mode: 'manual' });
    await act(async () => { await change; });
    expect(result.current.manualTurnTaking).toBe(true);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);

    act(() => result.current.startManualTurn());
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(false);
  });

  it('keeps the effective mode unchanged and fails locally muted on an unknown mode outcome', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'outcome_unknown', accepted: false, operation: 'turn_mode_update' });
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => {
      await expect(result.current.setManualTurnTaking(true)).rejects.toThrow('will not be retried automatically');
    });
    expect(result.current.manualTurnTaking).toBe(false);
    expect(result.current.muted).toBe(true);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
    expect(mocks.turnMode).toHaveBeenCalledTimes(1);
  });

  it('mutes before one stable manual commit and restores automatic mode only after ack', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    const commitAck = deferred<Record<string, unknown>>();
    mocks.manualCommit.mockReturnValueOnce(commitAck.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());

    let first!: Promise<void>;
    let duplicate!: Promise<void>;
    act(() => {
      first = result.current.commitManualTurn();
      duplicate = result.current.commitManualTurn();
    });
    expect(first).toBe(duplicate);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
    expect(mocks.manualCommit).toHaveBeenCalledTimes(1);
    expect(mocks.media[0].setMuted.mock.invocationCallOrder.at(-1))
      .toBeLessThan(mocks.manualCommit.mock.invocationCallOrder[0]);
    expect(mocks.manualCommit).toHaveBeenCalledWith(expect.stringMatching(/^manual-commit-/), 1);
    commitAck.resolve({ state: 'accepted' });
    await act(async () => { await first; });

    const automaticAck = deferred<Record<string, unknown>>();
    mocks.turnMode.mockReturnValueOnce(automaticAck.promise);
    let automatic!: Promise<void>;
    act(() => { automatic = result.current.setManualTurnTaking(false); });
    expect(result.current.manualTurnTaking).toBe(true);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
    automaticAck.resolve({ state: 'accepted', turn_mode: 'automatic' });
    await act(async () => { await automatic; });
    expect(result.current.manualTurnTaking).toBe(false);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(false);
  });

  it.each([
    [{ state: 'rejected', error: { code: 'audio_buffer_empty' } }, 'No audio was captured'],
    [{ state: 'outcome_unknown', accepted: false }, 'will not be retried automatically'],
  ])('surfaces recoverable manual commit result %# without automatic retry', async (ack, message) => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    mocks.manualCommit.mockResolvedValueOnce(ack);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());
    const first = result.current.commitManualTurn();
    const duplicate = result.current.commitManualTurn();
    expect(first).toBe(duplicate);
    await expect(first).rejects.toThrow(message);
    expect(mocks.manualCommit).toHaveBeenCalledTimes(1);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
  });

  it('fences a late manual acknowledgement after End Call', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    const commitAck = deferred<Record<string, unknown>>();
    mocks.manualCommit.mockReturnValueOnce(commitAck.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());
    const pending = result.current.commitManualTurn();
    act(() => result.current.close());
    commitAck.resolve({ state: 'accepted' });
    await expect(pending).rejects.toThrow('previous Realtime session');
    expect(mocks.manualCommit).toHaveBeenCalledTimes(1);
  });

  it('does not commit a discarded capture or a late release after a conversation switch', async () => {
    mocks.turnMode.mockResolvedValue({ state: 'accepted', turn_mode: 'manual' });
    const { result, rerender } = renderHook(
      ({ conversationId }) => useRealtimeSession({ enabled: true, target: 'fake', conversationId, getToken }),
      { initialProps: { conversationId: 'hvc_1' } },
    );
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => {
      result.current.startManualTurn();
      result.current.discardManualTurn();
    });
    await expect(result.current.commitManualTurn()).rejects.toThrow('Start recording');
    expect(mocks.manualCommit).not.toHaveBeenCalled();

    act(() => result.current.startManualTurn());
    const lateRelease = result.current.commitManualTurn;
    rerender({ conversationId: 'hvc_2' });
    await expect(lateRelease()).rejects.toThrow(/not ready|previous|Start recording/);
    expect(mocks.manualCommit).not.toHaveBeenCalled();
  });

  it('surfaces a control reconnect during commit and never resends automatically', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    const commitAck = deferred<Record<string, unknown>>();
    mocks.manualCommit.mockReturnValueOnce(commitAck.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());
    const pending = result.current.commitManualTurn();
    commitAck.reject(new Error('Realtime control connection closed'));
    await expect(pending).rejects.toThrow('connection closed');
    expect(mocks.manualCommit).toHaveBeenCalledTimes(1);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
  });

  it('suppresses the previous projection on the conversation-change render', async () => {
    const getToken = async () => null;
    const { result, rerender } = renderHook(
      ({ conversationId }) => useRealtimeSession({ enabled: true, target: 'fake', conversationId, getToken }),
      { initialProps: { conversationId: 'hvc_1' } },
    );
    await waitFor(() => expect(result.current.projection.workerJobs.job_old).toBeDefined());
    rerender({ conversationId: 'hvc_2' });
    expect(result.current.projection.workerJobs).toEqual({});
  });
});
