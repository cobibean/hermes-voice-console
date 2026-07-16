import { describe, expect, it } from 'vitest';
import { emptyRealtimeProjection } from './conversationProjection';
import { presentRealtimeJobs, realtimeReadiness } from './buildRealtimePresentation';
import type { RealtimeSessionController } from './useRealtimeSession';

function session(overrides: Partial<RealtimeSessionController> = {}): RealtimeSessionController {
  return {
    state: 'ready', compatibility: null, mediaState: 'connected', controlState: 'ready', connected: true,
    stateDetail: undefined, muted: false, manualTurnTaking: false, projection: emptyRealtimeProjection,
    connect: async () => undefined, close: () => undefined, setMuted: () => undefined,
    setManualTurnTaking: () => undefined, startManualTurn: () => undefined, stopManualTurn: () => undefined,
    sendInput: () => undefined, interruptSpeech: () => undefined, resolveApproval: () => undefined,
    workerCommand: () => undefined, ...overrides,
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
});
