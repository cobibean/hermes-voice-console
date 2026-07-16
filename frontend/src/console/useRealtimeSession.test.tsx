import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRealtimeSession } from './useRealtimeSession';

const mocks = vi.hoisted(() => ({
  approval: vi.fn(),
  controls: [] as Array<{ options: Record<string, any>; isReady: boolean }>,
}));

vi.mock('../lib/api', () => ({
  loadRealtimeCompatibility: vi.fn(async () => ({ compatible: true, version: '1.0', reasons: [], contract: {} })),
  createRealtimeSession: vi.fn(), activateRealtimeSession: vi.fn(), closeRealtimeSession: vi.fn(async () => undefined),
}));
vi.mock('../lib/realtimeClient', () => ({
  RealtimeClient: class {
    activeSession = {
      contract_version: '1.0', realtime_session_id: 'rt_1', conversation_id: 'hvc_1',
      session_generation: 1, state: 'active', answer_sdp: 'v=0', client_request_id: 'create_1',
    };
    isConnected = true;
    constructor(private options: { onState?: (state: string) => void }) {}
    async connect() { this.options.onState?.('connected'); return this.activeSession; }
    close() { return this.activeSession; }
    setMuted() {}
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

describe('useRealtimeSession approval and identity ownership', () => {
  beforeEach(() => { mocks.approval.mockReset(); mocks.controls.length = 0; });

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
