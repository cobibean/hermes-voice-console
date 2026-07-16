import { describe, expect, it } from 'vitest';
import { mergeConversationMessages, projectRealtimeEvent, projectRealtimeSnapshot, sanitizeArtifactHref } from './conversationProjection';

describe('Realtime conversation projection', () => {
  it('restores active jobs from a snapshot and does not redispatch anything', () => {
    const state = projectRealtimeSnapshot({
      conversation_id: 'hvc_1', last_event_id: 'ev_10',
      worker_jobs: [{ worker_job_id: 'job_1', status: 'running', task: 'Build it' }],
      approvals: [{ approval_id: 'approval_1', state: 'pending' }],
    });
    expect(state.workerJobs.job_1).toEqual(expect.objectContaining({ status: 'running' }));
    expect(state.approvals.approval_1).toEqual(expect.objectContaining({ state: 'pending' }));
  });

  it('normalizes the frozen Hermes transcript row shape', () => {
    const state = projectRealtimeSnapshot({
      conversation_id: 'hvc_1', last_event_id: 'rte_9',
      transcript: [
        { role: 'user', text: 'Build this', timestamp: 10 },
        { role: 'assistant', text: 'I am on it', timestamp: 11 },
      ],
    });
    expect(state.messages).toEqual([
      { role: 'user', content: 'Build this' },
      { role: 'assistant', content: 'I am on it' },
    ]);
  });

  it('deduplicates replayed event IDs while keeping entity-keyed worker state', () => {
    const initial = projectRealtimeSnapshot({ conversation_id: 'hvc_1', last_event_id: null });
    const event = { event_id: 'ev_1', type: 'worker.progress', conversation_id: 'hvc_1', payload: { worker_job_id: 'job_1', progress: 'halfway' } };
    const once = projectRealtimeEvent(initial, event);
    const twice = projectRealtimeEvent(once, event);
    expect(twice).toBe(once);
    expect(once.workerJobs.job_1).toEqual(expect.objectContaining({ progress: 'halfway' }));
  });

  it('closes a restored approval when its authoritative resolution event arrives', () => {
    const initial = projectRealtimeSnapshot({
      conversation_id: 'hvc_1', last_event_id: 'ev_1',
      pending_approvals: [{ approval_id: 'approval_1', state: 'pending', choices: ['once', 'deny'] }],
    });
    const resolved = projectRealtimeEvent(initial, {
      event_id: 'ev_2', type: 'approval.resolved', conversation_id: 'hvc_1',
      payload: { approval_id: 'approval_1' },
    });
    expect(resolved.approvals.approval_1.state).toBe('resolved');
  });

  it('projects provider transcripts into the correct speaker and tracks live activity', () => {
    let state = projectRealtimeSnapshot({ conversation_id: 'hvc_1', last_event_id: null });
    state = projectRealtimeEvent(state, { event_id: 'ev_1', type: 'speech.started', conversation_id: 'hvc_1', payload: {} });
    state = projectRealtimeEvent(state, { event_id: 'ev_2', type: 'user.transcript.completed', conversation_id: 'hvc_1', payload: { transcript: 'Hello Hermes' } });
    state = projectRealtimeEvent(state, { event_id: 'ev_3', type: 'hermes.transcript.delta', conversation_id: 'hvc_1', payload: { delta: 'Hi' } });
    state = projectRealtimeEvent(state, { event_id: 'ev_4', type: 'hermes.transcript.completed', conversation_id: 'hvc_1', payload: { transcript: 'Hi there' } });
    expect(state.messages).toEqual([{ role: 'user', content: 'Hello Hermes' }, { role: 'assistant', content: 'Hi there' }]);
    expect(state.listening).toBe(true);
    expect(state.speaking).toBe(true);
    state = projectRealtimeEvent(state, { event_id: 'ev_5', type: 'response.completed', conversation_id: 'hvc_1', payload: {} });
    expect(state.speaking).toBe(false);
  });

  it('allows only credential-free artifact links from configured origins', () => {
    expect(sanitizeArtifactHref('/artifacts/result.txt', ['http://localhost:3000'])).toBe('/artifacts/result.txt');
    expect(sanitizeArtifactHref('javascript:alert(1)', ['http://localhost:3000'])).toBeUndefined();
    expect(sanitizeArtifactHref('https://evil.example/result', ['http://localhost:3000'])).toBeUndefined();
    expect(sanitizeArtifactHref('http://user:pass@localhost:3000/result', ['http://localhost:3000'])).toBeUndefined();
  });

  it('keeps loaded history while avoiding snapshot overlap', () => {
    const history = [{ role: 'user' as const, content: 'old' }, { role: 'assistant' as const, content: 'reply' }];
    expect(mergeConversationMessages(history, [{ role: 'assistant', content: 'reply' }, { role: 'user', content: 'new' }]))
      .toEqual([...history, { role: 'user', content: 'new' }]);
  });
});
