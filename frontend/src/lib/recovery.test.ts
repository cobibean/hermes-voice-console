import { beforeEach, describe, expect, it } from 'vitest';
import { clearRecovery, loadRecovery, saveRecovery } from './recovery';

describe('run recovery metadata', () => {
  beforeEach(() => clearRecovery());

  it('stores only bounded versioned identifiers', () => {
    saveRecovery({
      target: 'jobhunter',
      conversationId: 'hvc_1',
      runId: 'run_1',
      lastSequence: 7,
    });
    const raw = window.sessionStorage.getItem('hvc.recovery.v1') ?? '';
    expect(raw).not.toContain('transcript');
    expect(raw).not.toContain('response');
    expect(loadRecovery()).toMatchObject({
      version: 1,
      target: 'jobhunter',
      conversationId: 'hvc_1',
      runId: 'run_1',
      lastSequence: 7,
    });
  });

  it('rejects malformed or expired metadata', () => {
    window.sessionStorage.setItem('hvc.recovery.v1', JSON.stringify({ version: 1 }));
    expect(loadRecovery()).toBeNull();
    expect(window.sessionStorage.getItem('hvc.recovery.v1')).toBeNull();
  });
});
