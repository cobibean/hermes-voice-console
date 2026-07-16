import type { ConsoleController } from '../useConsoleController';
import type { RealtimePresentationModel } from '../realtimePresentation';

export function Composer({
  controller,
  compact = false,
  realtime,
}: {
  controller: ConsoleController;
  compact?: boolean;
  realtime?: RealtimePresentationModel;
}) {
  const canContinueWhileWorking = realtime?.mode === 'realtime';
  const locked = Boolean(controller.acceptanceUnknown)
    || !controller.selectedTarget
    || !controller.sessionKey
    || (!canContinueWhileWorking && (
      controller.state.agent === 'running'
      || controller.state.agent === 'waiting_for_approval'
    ));
  return (
    <section className={compact ? 'composer composer-mobile' : 'composer card'} aria-label="Message composer">
      <textarea
        aria-label="Message to agent"
        placeholder={canContinueWhileWorking
          ? 'Keep talking to Hermes…'
          : 'Message Hermes…'}
        value={controller.textDraft}
        disabled={locked}
        onChange={(event) => controller.setTextDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            void controller.submitText();
          }
        }}
      />
      <button
        type="button"
        disabled={locked || !controller.textDraft.trim()}
        onClick={() => void controller.submitText()}
      >
        Send
      </button>
    </section>
  );
}
