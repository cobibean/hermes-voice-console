import type { ReactNode } from 'react';

export function ConsoleHeader({ accountControl }: { accountControl?: ReactNode }) {
  return (
    <header className="hero">
      <div>
        <p className="eyebrow">Standalone companion · no Hermes source patch</p>
        <h1>Hermes Voice Console</h1>
        <p>Browser mic → console STT → Hermes API Server → console TTS → browser playback.</p>
      </div>
      {accountControl ? <div className="account-control">{accountControl}</div> : null}
    </header>
  );
}
