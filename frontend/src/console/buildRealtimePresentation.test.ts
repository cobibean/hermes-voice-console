import { describe, expect, it } from 'vitest';
import { emptyRealtimeProjection, projectRealtimeSnapshot } from './conversationProjection';
import { describeRealtimeApproval, presentRealtimeJobs, realtimeReadiness, workerControlPayload } from './buildRealtimePresentation';
import { projectionForIdentity, type RealtimeSessionController } from './useRealtimeSession';

function session(overrides: Partial<RealtimeSessionController> = {}): RealtimeSessionController {
  return {
    state: 'ready', compatibility: null, mediaState: 'connected', controlState: 'ready', connected: true,
    stateDetail: undefined, muted: false, manualTurnTaking: false, projection: emptyRealtimeProjection,
    connect: async () => undefined, close: () => undefined, setMuted: () => undefined,
    setManualTurnTaking: () => undefined, startManualTurn: () => undefined, stopManualTurn: () => undefined,
    sendInput: async () => undefined, interruptSpeech: async () => undefined, resolveApproval: async () => undefined,
    submittingApprovalId: null, workerCommand: async () => undefined, ...overrides,
  };
}

describe('Realtime presentation adapter', () => {
  it('never reports live before authoritative control is ready', () => {
    expect(realtimeReadiness(session({ state: 'attaching_hermes', mediaState: 'connected', controlState: 'subscribing' }))).toBe('attaching_hermes');
    expect(realtimeReadiness(session())).toBe('live');
  });

  it('restores jobs and drops untrusted artifact links before presentation', () => {
    const projection = {
      ...emptyRealtimeProjection,
      workerJobs: { job_1: { worker_job_id: 'job_1', task: 'Build feature', status: 'running', revision: 3, artifacts: [
        { artifact_id: 'a1', filename: 'safe.txt', href: '/artifacts/safe.txt' },
        { artifact_id: 'a2', filename: 'unsafe.txt', href: 'javascript:alert(1)' },
      ] } },
    };
    const jobs = presentRealtimeJobs(session({ projection }), ['http://localhost:3000']);
    expect(jobs[0]).toEqual(expect.objectContaining({ id: 'job_1', title: 'Build feature', status: 'running' }));
    expect(jobs[0].artifacts?.[0].href).toBe('/artifacts/safe.txt');
    expect(jobs[0].artifacts?.[1].href).toBeUndefined();
  });

  it('normalizes frozen object task/completion and terminal attempt lineage', () => {
    const projection = {
      ...emptyRealtimeProjection,
      workerJobs: { job_2: {
        worker_job_id: 'job_2', task: { goal: 'Ship the bridge' }, status: 'outcome_unknown', revision: 4,
        completion: {
          summary: 'Process state could not be proven',
          results: [
            { status: 'completed', summary: 'Source updated' },
            { status: 'failed', summary: 'Live verification unavailable' },
          ],
        },
        attempts: [{ attempt_number: 2, supersedes_attempt_id: 'attempt_1', verification: 'unverified' }],
      } },
    };
    expect(presentRealtimeJobs(session({ projection }), [window.location.origin])[0]).toEqual(expect.objectContaining({
      title: 'Ship the bridge', status: 'failed',
      summary: 'Process state could not be proven · completed: Source updated · failed: Live verification unavailable',
      attempt: 2, parentAttemptId: 'attempt_1', verification: 'unverified',
    }));
  });

  it('matches the frozen worker-control wire payloads', () => {
    expect(workerControlPayload('refine', 'Keep the tests')).toEqual({ context: 'Keep the tests' });
    expect(workerControlPayload('redirect', 'Ship docs first')).toEqual({ goal: 'Ship docs first' });
    expect(workerControlPayload('cancel')).toEqual({});
  });

  it('suppresses the prior conversation projection during the identity-change paint', () => {
    const previous = { ...emptyRealtimeProjection, workerJobs: { old_job: { worker_job_id: 'old_job' } } };
    expect(projectionForIdentity(previous, 'target-a|conversation-a', 'target-a|conversation-b')).toBe(emptyRealtimeProjection);
    expect(projectionForIdentity(previous, 'target-a|conversation-a', 'target-a|conversation-a')).toBe(previous);
  });

  it('describes the exact durable Hermes reconnect approval without tool calls or arguments', () => {
    const projection = projectRealtimeSnapshot({
      conversation_id: 'conversation-1',
      last_event_id: null,
      pending_approvals: [{
        approval_id: 'approval-1',
        state: 'pending',
        tool_call_id: 'call-1',
        tool_name: 'run_shell',
        expires_at: 1_800_000_000,
      }],
    });

    expect(projection.toolCalls).toEqual({});
    expect(projection.approvals['approval-1']).toEqual({
      approval_id: 'approval-1',
      state: 'pending',
      tool_call_id: 'call-1',
      tool_name: 'run_shell',
      expires_at: 1_800_000_000,
    });
    const message = describeRealtimeApproval(
      projection.approvals['approval-1'],
      projection.toolCalls,
    );
    expect(message).toContain('Tool: run_shell.');
    expect(message).toContain('Expires: 2027-01-15T08:00:00.000Z.');
    expect(message).not.toContain('argument');
  });

  it('prefers the approval tool name and falls back to the durable tool call join', () => {
    expect(describeRealtimeApproval(
      { approval_id: 'approval_1', tool_call_id: 'call_1', tool_name: 'run_shell' },
      { call_1: { tool_call_id: 'call_1', tool_name: 'stale_name' } },
    )).toContain('Tool: run_shell.');
    expect(describeRealtimeApproval(
      { approval_id: 'approval_2', tool_call_id: 'call_2' },
      { call_2: { tool_call_id: 'call_2', tool_name: 'terminal' } },
    )).toContain('Tool: terminal.');
  });
});
