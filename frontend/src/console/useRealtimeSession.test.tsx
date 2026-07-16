import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { supportsManualTurnControls, useRealtimeSession } from './useRealtimeSession';

const mocks = vi.hoisted(() => ({
  approval: vi.fn(),
  compatibility: vi.fn(),
  createSession: vi.fn(),
  manualCommit: vi.fn(),
  manualDiscard: vi.fn(),
  turnMode: vi.fn(),
  media: [] as Array<{ setMuted: ReturnType<typeof vi.fn>; options: Record<string, any> }>,
  controls: [] as Array<{ options: Record<string, any>; isReady: boolean }>,
}));

vi.mock('../lib/api', () => ({
  loadRealtimeCompatibility: (...args: unknown[]) => mocks.compatibility(...args),
  createRealtimeSession: (...args: unknown[]) => mocks.createSession(...args),
  activateRealtimeSession: vi.fn(), closeRealtimeSession: vi.fn(async () => undefined),
}));
vi.mock('../lib/realtimeClient', () => ({
  RealtimeClient: class {
    activeSession: Record<string, any> = {
      contract_version: '1.0', realtime_session_id: 'rt_1', conversation_id: 'hvc_1',
      session_generation: 1, state: 'active', answer_sdp: 'v=0', client_request_id: 'create_1',
    };
    isConnected = true;
    setMuted = vi.fn();
    constructor(public options: Record<string, any>) { mocks.media.push(this); }
    async connect() {
      this.activeSession = await this.options.exchangeSdp('v=0');
      this.options.onState?.('connected');
      return this.activeSession;
    }
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
    manualAudioDiscard(...args: unknown[]) { return mocks.manualDiscard(...args); }
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
const supportedCompatibility = {
  compatible: true, version: '1.0', reasons: [],
  contract: { sessions: { manual_audio_commit: true, manual_audio_discard: true, turn_mode_update: true, turn_modes: ['server_vad', 'manual'] } },
};

describe('useRealtimeSession approval and identity ownership', () => {
  beforeEach(() => {
    mocks.approval.mockReset();
    mocks.compatibility.mockReset();
    mocks.compatibility.mockResolvedValue(supportedCompatibility);
    mocks.createSession.mockReset();
    mocks.createSession.mockImplementation(async (input: Record<string, unknown>) => ({
      contract_version: '1.0', realtime_session_id: `rt_${String(input.conversationId)}`,
      conversation_id: input.conversationId, session_generation: mocks.createSession.mock.calls.length, state: 'active',
      answer_sdp: 'v=0', client_request_id: input.clientRequestId,
    }));
    mocks.manualCommit.mockReset();
    mocks.manualDiscard.mockReset();
    mocks.turnMode.mockReset();
    mocks.controls.length = 0;
    mocks.media.length = 0;
  });

  it('requires every advertised manual-turn contract key', () => {
    expect(supportsManualTurnControls({
      compatible: true, version: '1.0', reasons: [],
      contract: { sessions: { manual_audio_commit: true, manual_audio_discard: true, turn_mode_update: true, turn_modes: ['server_vad', 'manual'] } },
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
    const lockedMuteCalls = mocks.media[0].setMuted.mock.calls.length;
    act(() => {
      result.current.setMuted(false);
      result.current.startManualTurn();
    });
    expect(result.current.muted).toBe(true);
    expect(mocks.media[0].setMuted).toHaveBeenCalledTimes(lockedMuteCalls);

    await act(async () => { await result.current.connect(); });
    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(result.current.manualControlsAvailable).toBe(true);
    act(() => result.current.setMuted(false));
    expect(result.current.muted).toBe(false);
    expect(mocks.media[1].setMuted).toHaveBeenLastCalledWith(false);
  });

  it('keeps the effective mode unchanged and visibly fails closed on the exact durable mode rejection', async () => {
    const rejected = deferred<Record<string, unknown>>();
    mocks.turnMode.mockReturnValueOnce(rejected.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    let first!: Promise<void>;
    let duplicate!: Promise<void>;
    act(() => {
      first = result.current.setManualTurnTaking(true);
      duplicate = result.current.setManualTurnTaking(true);
    });
    expect(first).toBe(duplicate);
    expect(mocks.turnMode).toHaveBeenCalledTimes(1);
    rejected.resolve({
      client_request_id: 'turn-mode-rejected-1', operation: 'turn_mode_update',
      state: 'rejected', accepted: false, error: { code: 'turn_mode_rejected' },
    });
    await act(async () => {
      await expect(first).rejects.toThrow('rejected the turn mode change');
    });
    expect(result.current.manualTurnTaking).toBe(false);
    expect(result.current.muted).toBe(true);
    expect(result.current.state).toBe('degraded');
    expect(result.current.stateDetail).toContain('rejected the turn mode change');
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
    await expect(result.current.setManualTurnTaking(true)).rejects.toThrow('Reconnect this Realtime call');
    expect(mocks.turnMode).toHaveBeenCalledTimes(1);
    const lockedMuteCalls = mocks.media[0].setMuted.mock.calls.length;
    act(() => {
      result.current.setMuted(false);
      result.current.startManualTurn();
    });
    expect(result.current.muted).toBe(true);
    expect(mocks.media[0].setMuted).toHaveBeenCalledTimes(lockedMuteCalls);

    await act(async () => { await result.current.connect(); });
    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(mocks.createSession).toHaveBeenCalledTimes(2);
    expect(result.current.manualControlsAvailable).toBe(true);
    act(() => result.current.setMuted(false));
    expect(result.current.muted).toBe(false);
    expect(mocks.media[1].setMuted).toHaveBeenLastCalledWith(false);
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
    expect(result.current.manualCaptureState).toBe('idle');

    mocks.manualCommit.mockResolvedValueOnce({ state: 'accepted' });
    act(() => result.current.startManualTurn());
    await act(async () => { await result.current.commitManualTurn(); });
    expect(mocks.manualCommit).toHaveBeenCalledTimes(2);
    expect(mocks.manualCommit.mock.calls[1][0]).not.toBe(mocks.manualCommit.mock.calls[0][0]);
    expect(result.current.manualCaptureState).toBe('idle');

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
    await waitFor(() => expect(result.current.manualCaptureState).toBe('error'));
    expect(result.current.manualCaptureError).toContain(message === 'No audio was captured' ? 'No audio was captured' : 'not be retried');
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

  it('waits for authoritative discard before clearing and requires a fresh capture before commit', async () => {
    mocks.turnMode.mockResolvedValue({ state: 'accepted', turn_mode: 'manual' });
    const discardAck = deferred<Record<string, unknown>>();
    mocks.manualDiscard.mockReturnValueOnce(discardAck.promise);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());
    let discard!: Promise<void>;
    act(() => { discard = result.current.discardManualTurn(); });
    expect(result.current.manualCaptureState).toBe('discarding');
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
    await expect(result.current.setManualTurnTaking(false)).rejects.toThrow('Finish or discard');
    expect(mocks.manualCommit).not.toHaveBeenCalled();
    discardAck.resolve({ state: 'accepted', audio_discard_requested: true });
    await act(async () => { await discard; });
    expect(result.current.manualCaptureState).toBe('idle');
    await expect(result.current.commitManualTurn()).rejects.toThrow('Start recording');

    mocks.manualCommit.mockResolvedValueOnce({ state: 'accepted' });
    act(() => result.current.startManualTurn());
    await act(async () => { await result.current.commitManualTurn(); });
    expect(mocks.manualDiscard.mock.invocationCallOrder[0])
      .toBeLessThan(mocks.manualCommit.mock.invocationCallOrder[0]);
  });

  it.each([
    [{ state: 'rejected', operation: 'manual_audio_discard', accepted: false, error: { code: 'audio_discard_rejected' } }, 'could not discard'],
    [{ state: 'outcome_unknown', operation: 'manual_audio_discard', accepted: false }, 'not be retried automatically'],
  ])('keeps failed or unknown discard visible without automatic retry %#', async (ack, message) => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    mocks.manualDiscard.mockResolvedValueOnce(ack);
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());
    const first = result.current.discardManualTurn();
    const duplicate = result.current.discardManualTurn();
    expect(first).toBe(duplicate);
    await expect(first).rejects.toThrow(message);
    expect(mocks.manualDiscard).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.manualCaptureState).toBe('error'));
    expect(result.current.manualCaptureRetryable).toBe(false);
    expect(result.current.state).toBe('degraded');
    await expect(result.current.setManualTurnTaking(false)).rejects.toThrow('Reconnect this Realtime call');
    expect(mocks.turnMode).toHaveBeenCalledTimes(1);
    act(() => result.current.startManualTurn());
    expect(result.current.manualCaptureState).toBe('error');
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(true);
    expect(result.current.projection.workerJobs.job_old).toBeDefined();

    await act(async () => { await result.current.connect(); });
    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(result.current.manualCaptureState).toBe('idle');
    expect(result.current.manualCaptureError).toBeUndefined();
    expect(result.current.projection.workerJobs.job_old).toBeDefined();
    expect(mocks.createSession).toHaveBeenCalledTimes(2);
    await expect(mocks.createSession.mock.results[1].value).resolves.toEqual(expect.objectContaining({ session_generation: 2 }));
  });

  it('treats Start recording as an explicit unmute action for a user-muted manual call', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    const { result } = renderHook(() => useRealtimeSession({
      enabled: true, target: 'fake', conversationId: 'hvc_1', getToken,
    }));
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.setMuted(true));
    expect(result.current.muted).toBe(true);
    act(() => result.current.startManualTurn());
    expect(result.current.manualCaptureState).toBe('capturing');
    expect(result.current.muted).toBe(false);
    expect(mocks.media[0].setMuted).toHaveBeenLastCalledWith(false);
  });

  it('fences a late discard acknowledgement after a target switch', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    const discardAck = deferred<Record<string, unknown>>();
    mocks.manualDiscard.mockReturnValueOnce(discardAck.promise);
    const { result, rerender } = renderHook(
      ({ target }) => useRealtimeSession({ enabled: true, target, conversationId: 'hvc_1', getToken }),
      { initialProps: { target: 'target-a' } },
    );
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    act(() => result.current.startManualTurn());
    const pending = result.current.discardManualTurn();
    rerender({ target: 'target-b' });
    discardAck.resolve({ state: 'accepted', audio_discard_requested: true });
    await expect(pending).rejects.toThrow('previous Realtime session');
    expect(result.current.manualCaptureState).toBe('idle');
    expect(result.current.manualCaptureError).toBeUndefined();
    expect(mocks.manualDiscard).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(result.current.state).toBe('ready'));
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
    expect(mocks.media.at(-1)!.setMuted).toHaveBeenLastCalledWith(true);
  });

  it('synchronously resets an old manual mode before creating a new conversation call', async () => {
    mocks.turnMode.mockResolvedValueOnce({ state: 'accepted', turn_mode: 'manual' });
    const { result, rerender } = renderHook(
      ({ conversationId }) => useRealtimeSession({ enabled: true, target: 'fake', conversationId, getToken }),
      { initialProps: { conversationId: 'hvc_1' } },
    );
    await waitFor(() => expect(result.current.state).toBe('ready'));
    await act(async () => { await result.current.setManualTurnTaking(true); });
    expect(result.current.manualTurnTaking).toBe(true);

    rerender({ conversationId: 'hvc_2' });
    expect(result.current.manualTurnTaking).toBe(false);
    expect(result.current.manualCaptureState).toBe('idle');
    await waitFor(() => expect(mocks.createSession).toHaveBeenCalledTimes(2));
    expect(mocks.createSession.mock.calls[1][0]).toEqual(expect.objectContaining({
      conversationId: 'hvc_2', turnMode: 'server_vad',
    }));
  });

  it('never reuses a supported target compatibility result for a pending or unsupported target', async () => {
    const targetB = deferred<Record<string, unknown>>();
    mocks.compatibility.mockImplementation((target: string) => (
      target === 'target-a' ? Promise.resolve(supportedCompatibility) : targetB.promise
    ));
    const { result, rerender } = renderHook(
      ({ target }) => useRealtimeSession({ enabled: true, target, conversationId: 'hvc_1', getToken }),
      { initialProps: { target: 'target-a' } },
    );
    await waitFor(() => expect(result.current.state).toBe('ready'));
    expect(mocks.createSession).toHaveBeenCalledTimes(1);

    rerender({ target: 'target-b' });
    expect(result.current.state).toBe('checking');
    expect(result.current.manualControlsAvailable).toBe(false);
    await expect(result.current.connect()).rejects.toThrow('preflight has not passed for this target');
    expect(mocks.createSession).toHaveBeenCalledTimes(1);

    targetB.resolve({ compatible: false, version: '1.0', reasons: ['manual endpoints missing'], contract: {} });
    await waitFor(() => expect(result.current.state).toBe('blocked'));
    expect(result.current.manualControlsAvailable).toBe(false);
    expect(mocks.createSession).toHaveBeenCalledTimes(1);
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
