import type { RealtimePresentationModel } from '../realtimePresentation';

const readinessCopy: Record<RealtimePresentationModel['readiness'], string> = {
  attaching_hermes: 'Audio is ready. Attaching Hermes control before the conversation starts.',
  blocked: 'Realtime is unavailable for this target.',
  connecting_audio: 'Connecting browser audio. Hermes is not live yet.',
  degraded: 'Audio or Hermes control was interrupted. Some realtime actions may be unavailable.',
  disconnected: 'The realtime call is disconnected.',
  live: 'Audio and Hermes control are ready.',
  recovering: 'Restoring audio and Hermes control. Delegated work continues separately.',
};

export function RealtimeStatusBar({ realtime }: { realtime?: RealtimePresentationModel }) {
  const mode = realtime?.mode ?? 'legacy';
  const readiness = realtime?.readiness ?? 'disconnected';
  const detail = realtime?.readinessDetail
    ?? (mode === 'legacy'
      ? 'Legacy turn-based fallback. Realtime voice is not active for this conversation.'
      : readinessCopy[readiness]);
  const recoverable = ['recovering', 'degraded', 'disconnected'].includes(readiness);
  const showRecoveryActions = recoverable || readiness === 'blocked';

  return (
    <section className={`realtime-status-wrap ${mode} readiness-${readiness}`} aria-label="Conversation mode">
      <div className="realtime-status" role="status" aria-live="polite">
        <div className="realtime-status-copy">
          <span className="connection-dot" aria-hidden="true" />
          <div>
            <strong>{mode === 'realtime' ? 'Realtime' : 'Legacy turn-based fallback'}</strong>
            <p>{detail}</p>
          </div>
        </div>
        {realtime?.mode === 'realtime' ? (
          <div className="realtime-presence" aria-label="Hermes voice activity">
            {realtime.listening ? <span>Listening</span> : null}
            {realtime.speaking ? <span>Speaking</span> : null}
            {!realtime.listening && !realtime.speaking && readiness === 'live' ? <span>Ready</span> : null}
          </div>
        ) : null}
      </div>
      {realtime && showRecoveryActions && (realtime.canReconnect || realtime.onUseLegacy) ? (
        <div className="realtime-status-actions" aria-label="Conversation recovery options">
          {recoverable && realtime.canReconnect && realtime.onReconnect ? (
            <button type="button" className="secondary touch-target" onClick={realtime.onReconnect}>Reconnect realtime</button>
          ) : null}
          {realtime.onUseLegacy ? (
            <button type="button" className="secondary touch-target" onClick={realtime.onUseLegacy}>Use Legacy turn-based fallback</button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
export function RealtimeVoiceControls({ realtime }: { realtime?: RealtimePresentationModel }) {
  if (!realtime || realtime.mode !== 'realtime') return null;
  const manualState = realtime.manualCaptureState ?? 'idle';
  const manualReady = realtime.readiness === 'live';
  const canStartManual = manualReady && Boolean(realtime.onStartManualTurn);
  const manualCopy = {
    error: realtime.manualCaptureError ?? 'Manual recording could not start. Try again when audio and Hermes control are ready.',
    idle: canStartManual
      ? 'Manual turns record only after Start recording. Send or discard when finished.'
      : 'Manual recording is unavailable until audio and Hermes control are ready.',
    capturing: 'Recording manually. Hermes will not receive this audio until you send it.',
    committing: 'Sending the recording to Hermes.',
    starting: 'Starting the microphone for a manual turn.',
  }[manualState];
  return (
    <section className="realtime-voice-controls" aria-label="Realtime voice controls">
      <button
        type="button"
        className={`${realtime.muted ? '' : 'secondary'} touch-target`}
        aria-pressed={realtime.muted}
        onClick={realtime.onToggleMute}
        disabled={!realtime.onToggleMute}
      >
        {realtime.muted ? 'Unmute mic' : 'Mute mic'}
      </button>
      <button
        type="button"
        className="secondary touch-target"
        aria-pressed={realtime.manualTurnTaking}
        onClick={realtime.onToggleManualTurnTaking}
        disabled={!realtime.onToggleManualTurnTaking}
      >
        {realtime.manualTurnTaking ? 'Switch to automatic turns' : 'Switch to manual turns'}
      </button>
      {realtime.manualTurnTaking ? (
        <div className="manual-capture-controls" role="group" aria-label="Manual recording">
          {manualState === 'idle' || manualState === 'error' ? (
            <button
              type="button"
              className="secondary touch-target"
              onClick={realtime.onStartManualTurn}
              disabled={!canStartManual}
            >
              {manualState === 'error' ? 'Try recording again' : 'Start recording'}
            </button>
          ) : null}
          {manualState === 'starting' ? (
            <button type="button" className="secondary touch-target" disabled aria-busy="true">Starting recording…</button>
          ) : null}
          {manualState === 'capturing' || manualState === 'committing' ? (
            <>
              <button
                type="button"
                className="secondary touch-target"
                onClick={realtime.onSendManualTurn}
                disabled={manualState === 'committing' || !realtime.onSendManualTurn}
                aria-busy={manualState === 'committing'}
              >
                {manualState === 'committing' ? 'Sending recording…' : 'Send recording'}
              </button>
              <button
                type="button"
                className="secondary touch-target"
                onClick={realtime.onDiscardManualTurn}
                disabled={manualState === 'committing' || !realtime.onDiscardManualTurn}
              >
                Discard recording
              </button>
            </>
          ) : null}
          <p className={manualState === 'error' ? 'manual-capture-error' : 'manual-capture-status'} role={manualState === 'error' ? 'alert' : 'status'}>
            {manualCopy}
          </p>
        </div>
      ) : null}
      <button
        type="button"
        className="secondary touch-target"
        onClick={realtime.onInterrupt}
        disabled={!realtime.speaking || !realtime.onInterrupt}
      >
        Interrupt Hermes
      </button>
      <button
        type="button"
        className="danger touch-target"
        onClick={realtime.onEndCall}
        disabled={!realtime.onEndCall}
      >
        End call
      </button>
      <p>{realtime.manualTurnTaking
        ? 'Interrupting Hermes speech keeps delegated work running.'
        : 'Automatic turns respond when you pause. Interrupting speech keeps delegated work running.'}</p>
    </section>
  );
}
