import type { Bootstrap } from '../lib/types';
import type { AgentState, PlaybackState, RecordingState } from '../lib/state';

export function DiagnosticsPanel({ bootstrap, recording, agent, playback, error, connected }: { bootstrap: Bootstrap | null; recording: RecordingState; agent: AgentState; playback: PlaybackState; error?: string; connected: boolean }) {
  return (
    <section className="card diagnostics">
      <h2>Diagnostics</h2>
      <dl>
        <dt>Connected</dt><dd>{connected ? 'yes' : 'no'}</dd>
        <dt>Recording</dt><dd>{recording}</dd>
        <dt>Agent</dt><dd>{agent}</dd>
        <dt>Playback</dt><dd>{playback}</dd>
        <dt>STT</dt><dd>{bootstrap?.voice.stt_provider ?? 'unknown'}</dd>
        <dt>TTS</dt><dd>{bootstrap?.voice.tts_provider ?? 'unknown'}</dd>
      </dl>
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
