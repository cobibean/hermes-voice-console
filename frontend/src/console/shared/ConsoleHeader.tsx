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
      <div>
        <p className="eyebrow">Hermes · persona and dispatcher</p>
        <h1>Hermes Voice Console</h1>
        <p>{realtime?.mode === 'realtime'
          ? 'Talk naturally while Hermes handles quick actions and delegates larger work.'
          : 'Conversational access to Hermes with turn-based voice and text.'}</p>
      </div>
      {accountControl ? <div className="account-control">{accountControl}</div> : null}
    </header>
  );
}
