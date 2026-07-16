import { describe, expect, it } from 'vitest';
import { emptyRealtimeProjection } from './conversationProjection';
import { presentRealtimeJobs, realtimeReadiness, workerControlPayload } from './buildRealtimePresentation';
import { projectionForIdentity, type RealtimeSessionController } from './useRealtimeSession';

function session(overrides: Partial<RealtimeSessionController> = {}): RealtimeSessionController {
  return {
    state: 'ready', compatibility: null, mediaState: 'connected', controlState: 'ready', connected: true,
    stateDetail: undefined, muted: false, manualTurnTaking: false, projection: emptyRealtimeProjection,
    connect: async () => undefined, close: () => undefined, setMuted: () => undefined,
    setManualTurnTaking: () => undefined, startManualTurn: () => undefined, stopManualTurn: () => undefined,
    sendInput: async () => undefined, interruptSpeech: async () => undefined, resolveApproval: async () => undefined,
    workerCommand: async () => undefined, ...overrides,
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
        completion: { summary: 'Process state could not be proven' },
        attempts: [{ attempt_number: 2, supersedes_attempt_id: 'attempt_1', verification: 'unverified' }],
      } },
    };
    expect(presentRealtimeJobs(session({ projection }), [window.location.origin])[0]).toEqual(expect.objectContaining({
      title: 'Ship the bridge', status: 'failed', summary: 'Process state could not be proven',
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
});
