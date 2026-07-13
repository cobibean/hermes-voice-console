import { DiagnosticsPanel } from '../components/DiagnosticsPanel';
import { RunTimeline } from '../components/RunTimeline';
import type { ConsoleController } from './useConsoleController';

export function ActivitySheet({ controller }: { controller: ConsoleController }) {
  if (!controller.bootstrap) return null;
  return (
    <section className="console-activity" data-testid="activity-sheet">
      <div className="button-row activity-actions">
        <button type="button" onClick={() => void controller.connect()}>Connect</button>
        <button type="button" onClick={controller.stopRun} disabled={!controller.state.activeRunId}>Stop run</button>
      </div>
      <DiagnosticsPanel
        bootstrap={controller.bootstrap}
        recording={controller.state.recording}
        agent={controller.state.agent}
        playback={controller.state.playback}
        error={controller.state.error ?? controller.loadError}
        connected={controller.connected}
      />
      <RunTimeline items={controller.timeline} />
    </section>
  );
}
