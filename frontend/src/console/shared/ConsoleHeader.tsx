import type { ReactNode } from 'react';
import type { RealtimePresentationModel } from '../realtimePresentation';

export function ConsoleHeader({
  accountControl,
  realtime,
}: {
  accountControl?: ReactNode;
  realtime?: RealtimePresentationModel;
}) {
  return (
    <header className="hero">
      <div className="hero-brand">
        <span className="hermes-mark" aria-hidden="true">☤</span>
        <div>
          <p className="eyebrow">Hermes · persona and dispatcher</p>
          <h1>Voice Console</h1>
          <p>{realtime?.mode === 'realtime'
            ? 'Talk naturally. Hermes stays with you while deeper work moves in parallel.'
            : 'A direct line to Hermes through voice and text.'}</p>
          <div className="hero-models" aria-label="Agent model roles">
            <span>Persona · GPT-Realtime 2.1</span>
            <span>Worker · GPT-5.6</span>
          </div>
        </div>
      </div>
      {accountControl ? <div className="account-control">{accountControl}</div> : null}
    </header>
  );
}
