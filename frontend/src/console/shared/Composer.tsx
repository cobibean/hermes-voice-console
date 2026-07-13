import type { ConsoleController } from '../useConsoleController';

export function Composer({ controller, compact = false }: { controller: ConsoleController; compact?: boolean }) {
  const locked = Boolean(controller.acceptanceUnknown)
    || controller.state.agent === 'running'
    || controller.state.agent === 'waiting_for_approval';
  return (
    <section className={compact ? 'composer composer-mobile' : 'composer card'} aria-label="Message composer">
      <textarea
        aria-label="Message to agent"
        placeholder="Ask the agent to do something…"
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
