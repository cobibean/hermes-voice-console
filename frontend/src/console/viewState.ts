import type { ConsoleMachineState } from '../lib/state';

export type ConsoleViewState =
  | 'disconnected'
  | 'connecting'
  | 'ready'
  | 'listening'
  | 'transcribing'
  | 'running'
  | 'waiting_for_approval'
  | 'speaking'
  | 'completed'
  | 'failed';

export function deriveConsoleViewState(
  state: ConsoleMachineState,
  connected: boolean,
): ConsoleViewState {
  if (state.error || state.agent === 'failed' || state.recording === 'error') return 'failed';
  if (state.agent === 'waiting_for_approval') return 'waiting_for_approval';
  if (state.recording === 'recording') return 'listening';
  if (state.recording === 'transcribing') return 'transcribing';
  if (state.recording === 'connecting') return 'connecting';
  if (state.playback === 'speaking' || state.playback === 'synthesizing') return 'speaking';
  if (state.agent === 'running') return 'running';
  if (state.agent === 'completed') return 'completed';
  return connected ? 'ready' : 'disconnected';
}
