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
  useEffect(() => setConfirmingAlways(false), [approval?.runId]);
  if (!approval) return null;
  const facts = approvalFacts(approval.payload);
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Approval request">
      <div className="modal-card">
        <h2>Hermes approval request</h2>
        <p>{approval.message}</p>
        {facts.length > 0 ? (
          <dl className="approval-facts">
            {facts.map(([label, value]) => (
              <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
            ))}
          </dl>
        ) : null}
        <p className="approval-scope">“Allow for this run” applies only to the current Hermes run. Deny blocks the pending action.</p>
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
              key={choice}
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
import { useEffect, useState } from 'react';
