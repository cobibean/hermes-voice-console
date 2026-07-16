import type { RealtimePresentationModel } from '../realtimePresentation';

const connectionCopy: Record<RealtimePresentationModel['connection'], string> = {
  blocked: 'Realtime unavailable',
  connecting: 'Connecting to Hermes',
  disconnected: 'Realtime disconnected',
  live: 'Hermes is live',
  recovering: 'Restoring conversation',
};

export function RealtimeStatusBar({ realtime }: { realtime?: RealtimePresentationModel }) {
  const mode = realtime?.mode ?? 'legacy';
  const connection = realtime?.connection ?? 'disconnected';
  const detail = realtime?.connectionDetail
    ?? (mode === 'legacy'
      ? 'Legacy turn-based fallback. Realtime voice is not active for this conversation.'
      : connectionCopy[connection]);

  return (
    <section
      className={`realtime-status ${mode} connection-${connection}`}
      aria-label="Conversation mode"
      role="status"
      aria-live="polite"
    >
      <div className="realtime-status-copy">
        <span className="connection-dot" aria-hidden="true" />
        <div>
          <strong>{mode === 'realtime' ? 'Realtime' : 'Legacy turn-based'}</strong>
          <p>{detail}</p>
        </div>
      </div>
      {realtime?.mode === 'realtime' ? (
        <div className="realtime-presence" aria-label="Hermes voice activity">
          {realtime.listening ? <span>Listening</span> : null}
          {realtime.speaking ? <span>Speaking</span> : null}
          {!realtime.listening && !realtime.speaking && connection === 'live' ? <span>Ready</span> : null}
        </div>
      ) : null}
      {realtime && (connection === 'disconnected' || connection === 'blocked') && realtime.onReconnect ? (
        <button type="button" className="secondary" onClick={realtime.onReconnect}>Reconnect</button>
      ) : null}
    </section>
  );
}
export function RealtimeVoiceControls({ realtime }: { realtime?: RealtimePresentationModel }) {
  if (!realtime || realtime.mode !== 'realtime') return null;
  return (
    <section className="realtime-voice-controls" aria-label="Realtime voice controls">
      <button
        type="button"
        className={realtime.muted ? undefined : 'secondary'}
        aria-pressed={realtime.muted}
        onClick={realtime.onToggleMute}
        disabled={!realtime.onToggleMute}
      >
        {realtime.muted ? 'Unmute mic' : 'Mute mic'}
      </button>
      <button
        type="button"
        className="secondary"
        aria-pressed={realtime.manualTurnTaking}
        onClick={realtime.onToggleManualTurnTaking}
        disabled={!realtime.onToggleManualTurnTaking}
      >
        {realtime.manualTurnTaking ? 'Manual turns on' : 'Automatic turns'}
      </button>
      <button
        type="button"
        className="secondary"
        onClick={realtime.onInterrupt}
        disabled={!realtime.speaking || !realtime.onInterrupt}
      >
        Interrupt Hermes
      </button>
      <p>Interrupting speech keeps delegated work running.</p>
    </section>
  );
}
