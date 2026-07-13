import { ApprovalModal } from '../../components/ApprovalModal';
import { SessionPicker } from '../../components/SessionPicker';
import { TargetPicker } from '../../components/TargetPicker';
import { TranscriptPanel } from '../../components/TranscriptPanel';
import { VoiceControls } from '../../components/VoiceControls';
import { ActivitySheet } from '../ActivitySheet';
import { RunInspector } from '../RunInspector';
import type { ConsoleController } from '../useConsoleController';

export function ConsoleContent({
  controller,
  variant,
}: {
  controller: ConsoleController;
  variant: 'desktop' | 'mobile';
}) {
  const bootstrap = controller.bootstrap;
  if (!bootstrap) return null;
  const selected = bootstrap.targets.find((target) => target.name === controller.selectedTarget);

  return (
    <>
      <section className="card grid two">
        <TargetPicker
          targets={bootstrap.targets}
          value={controller.selectedTarget}
          onChange={controller.selectTarget}
        />
        <SessionPicker value={controller.sessionKey} onChange={controller.selectSession} />
      </section>

      {selected && !selected.api_key_configured ? (
        <p className="warning">Selected target is missing its server-side API key env var.</p>
      ) : null}

      {controller.acceptanceUnknown ? (
        <section className="card warning" role="alert">
          <h2>Run acceptance is uncertain</h2>
          <p>{controller.acceptanceUnknown.message}</p>
          <button onClick={controller.acknowledgeAcceptanceUnknown}>
            Acknowledge risk and unlock
          </button>
        </section>
      ) : null}

      <VoiceControls
        recording={controller.state.recording}
        supported={controller.isCaptureSupported}
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

      <div className="grid two console-workspace">
        <TranscriptPanel messages={controller.messages} response={controller.response} />
        {variant === 'desktop' ? <RunInspector controller={controller} /> : <ActivitySheet controller={controller} />}
      </div>

      <section className="card button-row">
        <button onClick={() => void controller.connect()}>Connect / probe target</button>
        <button
          onClick={controller.stopRun}
          disabled={controller.state.agent !== 'running' && controller.state.agent !== 'waiting_for_approval'}
        >
          Stop current Hermes run
        </button>
      </section>

      <ApprovalModal approval={controller.approval} onResolve={controller.resolveApproval} />
    </>
  );
}
