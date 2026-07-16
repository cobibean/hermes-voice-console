import type { RealtimePresentationModel, WorkerJobPresentation } from '../console/realtimePresentation';

const statusCopy: Record<WorkerJobPresentation['status'], string> = {
  awaiting_approval: 'Needs approval',
  cancelled: 'Cancelled',
  completed: 'Completed',
  failed: 'Needs attention',
  queued: 'Queued',
  running: 'In progress',
};

function safeProgress(progress?: number): number | undefined {
  if (typeof progress !== 'number') return undefined;
  return Math.max(0, Math.min(100, Math.round(progress)));
}
function WorkerJobCard({ job, realtime }: { job: WorkerJobPresentation; realtime: RealtimePresentationModel }) {
  const progress = safeProgress(job.progress);
  return (
    <article className={`worker-job status-${job.status}`} aria-labelledby={`job-${job.id}-title`}>
      <header className="worker-job-header">
        <div>
          <p className="worker-job-kicker">Delegated task</p>
          <h3 id={`job-${job.id}-title`}>{job.title}</h3>
        </div>
        <span className={`job-status status-${job.status}`} role="status">{statusCopy[job.status]}</span>
      </header>
      {job.summary ? <p className="worker-job-summary">{job.summary}</p> : null}
      <div className="worker-job-meta" aria-label="Task details">
        {typeof job.queuePosition === 'number' && job.status === 'queued' ? <span>Queue position {job.queuePosition}</span> : null}
        {typeof job.attempt === 'number' ? <span>Attempt {job.attempt}</span> : null}
        {job.parentAttemptId ? <span>Continues attempt {job.parentAttemptId}</span> : null}
      </div>
      {progress !== undefined ? (
        <div className="job-progress">
          <div className="job-progress-copy"><span>Progress</span><span>{progress}%</span></div>
          <progress value={progress} max="100" aria-label={`${job.title} progress`}>{progress}%</progress>
        </div>
      ) : null}
      {job.approvalMessage ? (
        <p className="job-approval"><strong>Approval required:</strong> {job.approvalMessage}</p>
      ) : null}
      {job.tools && job.tools.length > 0 ? (
        <div className="job-tools" aria-label="Tool activity">
          <strong>Tool activity</strong>
          <ul>
            {job.tools.map((tool) => (
              <li key={tool.id} className={`status-${tool.status}`}>
                <span>{tool.label}</span>
                <small>{tool.detail ?? tool.status}</small>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {job.artifacts && job.artifacts.length > 0 ? (
        <div className="job-artifacts" aria-label="Artifacts">
          <strong>Artifacts</strong>
          <ul>
            {job.artifacts.map((artifact) => (
              <li key={artifact.id}>
                {artifact.href ? <a href={artifact.href}>{artifact.label}</a> : <span>{artifact.label}</span>}
                {artifact.kind ? <small>{artifact.kind}</small> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {job.verification ? <p className="job-verification"><strong>Verified:</strong> {job.verification}</p> : null}
      <footer className="worker-job-actions" aria-label={`Controls for ${job.title}`}>
        <button type="button" className="secondary" onClick={() => realtime.onRequestStatus?.(job.id)} disabled={!realtime.onRequestStatus}>Status</button>
        <button type="button" className="secondary" onClick={() => realtime.onRefine?.(job.id)} disabled={!realtime.onRefine}>Refine</button>
        <button type="button" className="secondary" onClick={() => realtime.onRedirect?.(job.id)} disabled={!realtime.onRedirect}>Redirect</button>
        <button
          type="button"
          className="secondary"
          onClick={() => realtime.onCancel?.(job.id)}
          disabled={!realtime.onCancel || !['queued', 'running', 'awaiting_approval'].includes(job.status)}
        >
          Cancel
        </button>
      </footer>
    </article>
  );
}

export function WorkerJobFeed({ realtime }: { realtime?: RealtimePresentationModel }) {
  if (!realtime || realtime.mode !== 'realtime') return null;
  return (
    <section className="worker-job-feed" aria-label="Delegated tasks">
      <div className="worker-job-feed-heading">
        <div>
          <p className="eyebrow">Working in the background</p>
          <h2>Delegated tasks</h2>
        </div>
        <span>{realtime.jobs.length}</span>
      </div>
      {realtime.jobs.length === 0 ? (
        <p className="worker-job-empty">No delegated work yet. Hermes will send larger tasks here while the conversation stays open.</p>
      ) : (
        <div className="worker-job-list">
          {realtime.jobs.map((job) => <WorkerJobCard key={job.id} job={job} realtime={realtime} />)}
        </div>
      )}
    </section>
  );
}
