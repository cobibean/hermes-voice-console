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

  it('rejects attacker-controlled identifiers, cursors, and expiry extension', () => {
    const savedAt = Date.now();
    for (const override of [
      { target: '../other-owner' },
      { runId: 'r'.repeat(129) },
      { lastSequence: -1 },
      { lastSequence: 1.5 },
      { expiresAt: savedAt + 24 * 60 * 60 * 1000 },
    ]) {
      window.sessionStorage.setItem('hvc.recovery.v1', JSON.stringify({
        version: 1,
        target: 'jobhunter',
        conversationId: 'hvc_1',
        runId: 'run_1',
        lastSequence: 7,
        savedAt,
        expiresAt: savedAt + 2 * 60 * 60 * 1000,
        ...override,
      }));
      expect(loadRecovery()).toBeNull();
      expect(window.sessionStorage.getItem('hvc.recovery.v1')).toBeNull();
    }
  });

  it('refuses to persist invalid recovery data even when called from untyped code', () => {
    expect(() => saveRecovery({
      target: 'jobhunter', conversationId: 'hvc_1', runId: '../run', lastSequence: 0,
    })).toThrow('bounded identifiers');
  });
});
