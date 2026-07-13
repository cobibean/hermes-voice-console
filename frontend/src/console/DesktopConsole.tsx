import type { ReactNode } from 'react';
import { ApprovalModal } from '../components/ApprovalModal';
import { TargetPicker } from '../components/TargetPicker';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { VoiceControls } from '../components/VoiceControls';
import { StatusAnnouncer } from '../components/StatusAnnouncer';
import { RunInspector } from './RunInspector';
import { Composer } from './shared/Composer';
import { ConsoleHeader } from './shared/ConsoleHeader';
import type { ConsoleController } from './useConsoleController';

export function DesktopConsole({
  controller,
  accountControl,
  notice,
}: {
  controller: ConsoleController;
  accountControl?: ReactNode;
  notice?: ReactNode;
}) {
  const bootstrap = controller.bootstrap;
  if (!bootstrap) return null;
  const selected = bootstrap.targets.find((target) => target.name === controller.selectedTarget);
  return (
    <main className="shell desktop-console" data-console-shell="desktop" data-view-state={controller.viewState}>
      <ConsoleHeader accountControl={accountControl} />
      <StatusAnnouncer status={controller.viewState} />
      {notice}
      <div className="desktop-command-grid">
        <aside className="session-rail card" aria-label="Conversations">
          <TargetPicker targets={bootstrap.targets} value={controller.selectedTarget} onChange={controller.selectTarget} />
          <div className="rail-heading">
            <h2>Conversations</h2>
            <button type="button" onClick={() => void controller.newConversation()}>New</button>
          </div>
          <nav className="conversation-list">
            {controller.sessions.map((session) => (
              <button
                type="button"
                key={session.conversation_id}
                className={session.conversation_id === controller.sessionKey ? 'active' : undefined}
                onClick={() => controller.selectSession(session.conversation_id)}
              >
                {session.title}
              </button>
            ))}
          </nav>
          {selected?.configured_provider_label || selected?.configured_model_label ? (
            <p className="operator-label">
              Configured: {[selected.configured_provider_label, selected.configured_model_label].filter(Boolean).join(' · ')}
            </p>
          ) : null}
        </aside>

        <section className="conversation-workspace">
          {selected && !selected.api_key_configured ? <p className="warning">This target is missing its server-side Hermes API key.</p> : null}
          {controller.acceptanceUnknown ? (
            <section className="card warning" role="alert">
              <h2>Run requires acknowledgement</h2>
              <p>{controller.acceptanceUnknown.message}</p>
              <button onClick={controller.acknowledgeAcceptanceUnknown}>Acknowledge risk and unlock</button>
            </section>
          ) : null}
          <TranscriptPanel transcript={controller.transcript} response={controller.response} />
          <Composer controller={controller} />
          <VoiceControls
            recording={controller.state.recording}
            supported={controller.isCaptureSupported}
            speakReplies={controller.speakReplies}
            onSpeakReplies={controller.setSpeakReplies}
            onStart={controller.startRecording}
            onStop={controller.stopRecording}
            onDiscard={controller.discardRecording}
            onCancelSpeech={controller.cancelSpeech}
            inputLevel={controller.inputLevel}
            elapsed={controller.recordingElapsed}
            maxSeconds={bootstrap.voice.max_recording_seconds}
            speechFallbackAvailable={controller.speechFallbackAvailable}
            onRetrySpeech={controller.retrySpeech}
          />
        </section>

        <aside className="desktop-inspector">
          <div className="card inspector-heading">
            <p className="eyebrow">Live run</p>
            <h2>{controller.viewState.replaceAll('_', ' ')}</h2>
            <div className="button-row">
              <button onClick={() => void controller.connect()}>Connect</button>
              <button onClick={controller.stopRun} disabled={!controller.state.activeRunId}>Stop run</button>
            </div>
          </div>
          <RunInspector controller={controller} />
        </aside>
      </div>
      <ApprovalModal approval={controller.approval} onResolve={controller.resolveApproval} />
    </main>
  );
}
