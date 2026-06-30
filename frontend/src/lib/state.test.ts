import { describe, expect, it } from 'vitest';
import { consoleReducer, initialConsoleState } from './state';

describe('consoleReducer', () => {
  it('tracks recording and transcript completion', () => {
    let state = consoleReducer(initialConsoleState, { type: 'recording.start', turnId: 't1' });
    expect(state.recording).toBe('connecting');
    state = consoleReducer(state, { type: 'event', event: { type: 'recording.started', turn_id: 't1' } });
    expect(state.recording).toBe('recording');
    state = consoleReducer(state, { type: 'recording.stop' });
    expect(state.recording).toBe('transcribing');
    state = consoleReducer(state, { type: 'event', event: { type: 'transcript.final', turn_id: 't1', text: 'hello' } });
    expect(state.recording).toBe('idle');
  });

  it('tracks approval and completion states', () => {
    let state = consoleReducer(initialConsoleState, { type: 'event', event: { type: 'agent.run.started', run_id: 'r1', session_id: 's1' } });
    expect(state.agent).toBe('running');
    state = consoleReducer(state, { type: 'event', event: { type: 'agent.approval.request', run_id: 'r1', approval: { message: 'Approve?' } } });
    expect(state.agent).toBe('waiting_for_approval');
    state = consoleReducer(state, { type: 'event', event: { type: 'agent.completed', run_id: 'r1', text: 'done' } });
    expect(state.agent).toBe('completed');
  });
});
