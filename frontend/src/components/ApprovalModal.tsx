import { useEffect, useRef, useState } from 'react';

export interface PendingApproval {
  runId: string;
  message: string;
  choices: Array<'once' | 'session' | 'always' | 'deny'>;
  payload: Record<string, unknown>;
  submitting?: boolean;
}

function approvalFacts(payload: Record<string, unknown>): Array<[string, string]> {
  const fields: Array<[string, unknown]> = [
    ['Tool', payload.tool],
    ['Operation', payload.operation ?? payload.command],
    ['Path or host', payload.path ?? payload.host],
    ['Reason', payload.reason],
  ];
  return fields
    .filter((entry): entry is [string, string | number | boolean] =>
      ['string', 'number', 'boolean'].includes(typeof entry[1]) && String(entry[1]).trim().length > 0)
    .map(([label, value]) => [label, String(value)]);
}

const LABELS: Record<string, string> = {
  once: 'Approve once',
  session: 'Allow for this run',
  always: 'Permanently allow',
  deny: 'Deny',
};

export function ApprovalModal({ approval, onResolve }: { approval: PendingApproval | null; onResolve: (decision: 'once' | 'session' | 'always' | 'deny') => void }) {
  const [confirmingAlways, setConfirmingAlways] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const denyButtonRef = useRef<HTMLButtonElement>(null);
  const approvalRunId = approval?.runId;

  useEffect(() => setConfirmingAlways(false), [approvalRunId]);
  useEffect(() => {
    if (!approvalRunId) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const composer = document.querySelector<HTMLElement>('[aria-label="Message to agent"]');
    const frame = window.requestAnimationFrame(() => {
      const firstButton = dialogRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)');
      (denyButtonRef.current ?? firstButton)?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      const returnTarget = previouslyFocused && previouslyFocused !== document.body
        ? previouslyFocused
        : composer;
      returnTarget?.focus();
    };
  }, [approvalRunId]);

  if (!approval) return null;
  const facts = approvalFacts(approval.payload);

  const containFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      denyButtonRef.current?.focus();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), summary, [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])') ?? [],
    ).filter((element) => !element.hasAttribute('hidden'));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="modal" role="presentation">
      <div
        ref={dialogRef}
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-title"
        aria-describedby="approval-message approval-scope"
        onKeyDown={containFocus}
      >
        <h2 id="approval-title">Hermes approval request</h2>
        <p id="approval-message">{approval.message}</p>
        {facts.length > 0 ? (
          <dl className="approval-facts">
            {facts.map(([label, value]) => (
              <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
            ))}
          </dl>
        ) : null}
        <p className="approval-scope" id="approval-scope">“Allow for this run” applies only to the current Hermes run. Deny blocks the pending action.</p>
        <details>
          <summary>Additional approval details</summary>
          <pre>{JSON.stringify(approval.payload, null, 2)}</pre>
        </details>
        {confirmingAlways ? (
          <p className="warning">
            This permanently changes the target agent&apos;s command allowlist. Confirm only if you want future matching actions allowed.
          </p>
        ) : null}
        <div className="button-row">
          {approval.choices.map((choice) => (
            <button
              type="button"
              key={choice}
              ref={choice === 'deny' ? denyButtonRef : undefined}
              disabled={approval.submitting}
              className={choice === 'deny' ? 'danger' : undefined}
              onClick={() => {
                if (choice === 'always' && !confirmingAlways) {
                  setConfirmingAlways(true);
                  return;
                }
                onResolve(choice);
              }}
            >
              {approval.submitting
                ? 'Submitting…'
                : choice === 'always' && confirmingAlways
                  ? 'Confirm permanent allow'
                  : LABELS[choice]}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
