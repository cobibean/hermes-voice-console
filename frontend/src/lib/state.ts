import type { VoiceServerEvent } from './types';

export type RecordingState = 'idle' | 'connecting' | 'recording' | 'transcribing' | 'error';
export type AgentState = 'idle' | 'running' | 'waiting_for_approval' | 'completed' | 'failed' | 'stopped';
export type PlaybackState = 'idle' | 'synthesizing' | 'speaking' | 'error';

export interface ConsoleMachineState {
  recording: RecordingState;
  agent: AgentState;
  playback: PlaybackState;
  activeTurnId?: string;
  activeRunId?: string;
  error?: string;
}

export const initialConsoleState: ConsoleMachineState = {
  recording: 'idle',
  agent: 'idle',
  playback: 'idle',
};

export type ConsoleAction =
  | { type: 'recording.start'; turnId: string }
  | { type: 'recording.started' }
  | { type: 'recording.stop' }
  | { type: 'recording.discard' }
  | { type: 'event'; event: VoiceServerEvent }
  | { type: 'playback.cancel' }
  | { type: 'error'; message: string }
  | { type: 'reset' };

export function consoleReducer(state: ConsoleMachineState, action: ConsoleAction): ConsoleMachineState {
  switch (action.type) {
    case 'recording.start':
      return { ...state, recording: 'connecting', activeTurnId: action.turnId, error: undefined };
    case 'recording.started':
      return { ...state, recording: 'recording' };
    case 'recording.stop':
      return { ...state, recording: 'transcribing' };
    case 'recording.discard':
      return { ...state, recording: 'idle', activeTurnId: undefined };
    case 'playback.cancel':
      return { ...state, playback: 'idle' };
    case 'error':
      return { ...state, recording: 'error', error: action.message };
    case 'reset':
      return initialConsoleState;
    case 'event': {
      const event = action.event;
      if (event.type === 'recording.started') return { ...state, recording: 'recording', activeTurnId: event.turn_id };
      if (event.type === 'recording.stopped') return { ...state, recording: 'transcribing' };
      if (event.type === 'recording.discarded') return { ...state, recording: 'idle', activeTurnId: undefined };
      if (event.type === 'transcript.final') return { ...state, recording: 'idle' };
      if (event.type === 'agent.run.started') return { ...state, agent: 'running', activeRunId: event.run_id };
      if (event.type === 'agent.approval.request') return { ...state, agent: 'waiting_for_approval', activeRunId: event.run_id };
      if (event.type === 'agent.approval.responded' || event.type === 'agent.approval.resolved') return { ...state, agent: 'running', activeRunId: event.run_id };
      if (event.type === 'agent.completed') return { ...state, agent: 'completed', activeRunId: undefined };
      if (event.type === 'agent.failed') return { ...state, agent: 'failed', activeRunId: undefined, error: event.error };
      if (event.type === 'agent.stopped') return { ...state, agent: 'stopped', activeRunId: undefined };
      if (event.type === 'agent.stop.requested') return { ...state, agent: 'stopped', activeRunId: event.run_id };
      if (event.type === 'tts.start') return { ...state, playback: 'synthesizing' };
      if (event.type === 'tts.complete') return { ...state, playback: 'idle' };
      if (event.type === 'error') return { ...state, error: event.message, recording: event.recoverable ? (state.recording === 'transcribing' ? 'idle' : state.recording) : 'error' };
      return state;
    }
  }
}

let turnSeq = 0;
export function nextTurnId(): string {
  turnSeq += 1;
  return `vturn_${Date.now()}_${turnSeq}`;
}
