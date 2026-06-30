export interface PendingApproval {
  runId: string;
  message: string;
  choices: Array<'once' | 'session' | 'always' | 'deny'>;
  payload: Record<string, unknown>;
  submitting?: boolean;
}

const LABELS: Record<string, string> = {
  once: 'Approve once',
  session: 'Approve for session',
  always: 'Always allow',
  deny: 'Deny',
};

export function ApprovalModal({ approval, onResolve }: { approval: PendingApproval | null; onResolve: (decision: 'once' | 'session' | 'always' | 'deny') => void }) {
  if (!approval) return null;
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Approval request">
      <div className="modal-card">
        <h2>Hermes approval request</h2>
        <p>{approval.message}</p>
        <details>
          <summary>Raw approval payload</summary>
          <pre>{JSON.stringify(approval.payload, null, 2)}</pre>
        </details>
        <div className="button-row">
          {approval.choices.map((choice) => (
            <button key={choice} disabled={approval.submitting} className={choice === 'deny' ? 'danger' : undefined} onClick={() => onResolve(choice)}>
              {approval.submitting ? 'Submitting…' : LABELS[choice]}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
