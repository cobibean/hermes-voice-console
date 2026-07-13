import { DiagnosticsPanel } from '../components/DiagnosticsPanel';
import { RunTimeline } from '../components/RunTimeline';
import type { ConsoleController } from './useConsoleController';

export function RunInspector({ controller }: { controller: ConsoleController }) {
  if (!controller.bootstrap) return null;
  return (
    <div className="console-inspector" data-testid="run-inspector">
      <DiagnosticsPanel
        bootstrap={controller.bootstrap}
        recording={controller.state.recording}
        agent={controller.state.agent}
        playback={controller.state.playback}
        error={controller.state.error ?? controller.loadError}
        connected={controller.connected}
      />
      <RunTimeline items={controller.timeline} />
    </div>
  );
}
