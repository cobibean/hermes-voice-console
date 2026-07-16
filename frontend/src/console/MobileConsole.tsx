import type { CSSProperties, ReactNode } from 'react';
import { ApprovalModal } from '../components/ApprovalModal';
import { TargetPicker } from '../components/TargetPicker';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { VoiceControls } from '../components/VoiceControls';
import { WorkerJobFeed } from '../components/WorkerJobFeed';
import { StatusAnnouncer } from '../components/StatusAnnouncer';
import { ActivitySheet } from './ActivitySheet';
import { Composer } from './shared/Composer';
import { RealtimeStatusBar, RealtimeVoiceControls } from './shared/RealtimeStatusBar';
import type { ConsoleController } from './useConsoleController';
import { MOBILE_TOUCH_TARGET_PX, type RealtimePresentationModel } from './realtimePresentation';

export function MobileConsole({
  controller,
  accountControl,
  notice,
  realtime,
}: {
  controller: ConsoleController;
  accountControl?: ReactNode;
  notice?: ReactNode;
  realtime?: RealtimePresentationModel;
}) {
  const bootstrap = controller.bootstrap;
  if (!bootstrap) return null;
  return (
    <main
      className="mobile-console"
      data-console-shell="mobile"
      data-view-state={controller.viewState}
      style={{ '--mobile-touch-target': `${MOBILE_TOUCH_TARGET_PX}px` } as CSSProperties}
    >
      <header className="mobile-header">
        <div className="mobile-brand">
          <span className="hermes-mark hermes-mark-mobile" aria-hidden="true">☤</span>
          <div>
            <p className="eyebrow">Hermes · Voice</p>
            <strong>{controller.viewState.replaceAll('_', ' ')}</strong>
          </div>
        </div>
        {accountControl}
      </header>
      <StatusAnnouncer status={controller.viewState} />
      {notice}
      <RealtimeStatusBar realtime={realtime} />
      <details className="mobile-settings card">
        <summary>Agent and conversation</summary>
        <TargetPicker targets={bootstrap.targets} value={controller.selectedTarget} onChange={controller.selectTarget} />
        <label className="field">
          Conversation
          <select value={controller.sessionKey} onChange={(event) => controller.selectSession(event.target.value)}>
            {controller.sessions.map((session) => <option key={session.conversation_id} value={session.conversation_id}>{session.title}</option>)}
          </select>
        </label>
        <button type="button" onClick={() => void controller.newConversation()}>New conversation</button>
      </details>
      {controller.acceptanceUnknown ? (
        <section className="mobile-risk warning" role="alert">
          <strong>Run requires acknowledgement</strong>
          <p>{controller.acceptanceUnknown.message}</p>
          <button onClick={controller.acknowledgeAcceptanceUnknown}>Acknowledge risk and unlock</button>
        </section>
      ) : null}
      <section className="mobile-conversation">
        <TranscriptPanel messages={controller.messages} response={controller.response} />
        <WorkerJobFeed realtime={realtime} />
        <p className="ai-voice-disclosure mobile-ai-disclosure">Spoken replies use an AI-generated voice.</p>
      </section>
      <details className="mobile-activity card">
        <summary>Activity and diagnostics</summary>
        <ActivitySheet controller={controller} />
      </details>
      {realtime?.mode === 'realtime' ? (
        <RealtimeVoiceControls realtime={realtime} />
      ) : (
        <VoiceControls
          recording={controller.state.recording}
          supported={controller.isCaptureSupported}
          ready={Boolean(controller.selectedTarget && controller.sessionKey)}
          speakReplies={controller.speakReplies}
          onSpeakReplies={controller.setSpeakReplies}
          onStart={controller.startRecording}
          onStop={controller.stopRecording}
          onCancelSpeech={controller.cancelSpeech}
          inputLevel={controller.inputLevel}
          elapsed={controller.recordingElapsed}
          maxSeconds={bootstrap.voice.max_recording_seconds}
          speechFallbackAvailable={controller.speechFallbackAvailable}
          onRetrySpeech={controller.retrySpeech}
        />
      )}
      <div className="mobile-composer-dock"><Composer controller={controller} compact realtime={realtime} /></div>
      <ApprovalModal approval={controller.approval} onResolve={controller.resolveApproval} />
    </main>
  );
}
