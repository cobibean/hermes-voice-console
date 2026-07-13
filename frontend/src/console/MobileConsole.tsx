import type { ReactNode } from 'react';
import { ApprovalModal } from '../components/ApprovalModal';
import { TargetPicker } from '../components/TargetPicker';
import { TranscriptPanel } from '../components/TranscriptPanel';
import { VoiceControls } from '../components/VoiceControls';
import { ActivitySheet } from './ActivitySheet';
import { Composer } from './shared/Composer';
import type { ConsoleController } from './useConsoleController';

export function MobileConsole({
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
  return (
    <main className="mobile-console" data-console-shell="mobile" data-view-state={controller.viewState}>
      <header className="mobile-header">
        <div>
          <p className="eyebrow">Hermes Voice Console</p>
          <strong>{controller.viewState.replaceAll('_', ' ')}</strong>
        </div>
        {accountControl}
      </header>
      {notice}
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
        <TranscriptPanel transcript={controller.transcript} response={controller.response} />
      </section>
      <details className="mobile-activity card">
        <summary>Activity and diagnostics</summary>
        <ActivitySheet controller={controller} />
      </details>
      <VoiceControls
        recording={controller.state.recording}
        supported={controller.isCaptureSupported}
        speakReplies={controller.speakReplies}
        onSpeakReplies={controller.setSpeakReplies}
        onStart={controller.startRecording}
        onStop={controller.stopRecording}
        onCancelSpeech={controller.cancelSpeech}
      />
      <div className="mobile-composer-dock"><Composer controller={controller} compact /></div>
      <ApprovalModal approval={controller.approval} onResolve={controller.resolveApproval} />
    </main>
  );
}
