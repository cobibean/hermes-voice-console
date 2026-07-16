import type { RealtimePresentationModel, WorkerJobPresentation, WorkerJobStatus } from './realtimePresentation';
import { sanitizeArtifactHref } from './conversationProjection';
import type { RealtimeSessionController } from './useRealtimeSession';

const JOB_STATUSES = new Set<WorkerJobStatus>(['queued', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled']);

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}
function number(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function presentRealtimeJobs(
  session: RealtimeSessionController,
  artifactAllowedOrigins: readonly string[],
): WorkerJobPresentation[] {
  const { workerJobs, toolCalls, approvals } = session.projection;
  return Object.values(workerJobs).map((job) => {
    const id = text(job.worker_job_id) ?? 'unknown-job';
    const rawStatus = text(job.status);
    const status: WorkerJobStatus = rawStatus && JOB_STATUSES.has(rawStatus as WorkerJobStatus)
      ? rawStatus as WorkerJobStatus
      : rawStatus === 'waiting_for_approval' ? 'awaiting_approval' : 'running';
    const attempts = Array.isArray(job.attempts) ? job.attempts.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    const latestAttempt = attempts.at(-1);
    const artifacts = (Array.isArray(job.artifacts) ? job.artifacts : [])
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
      .map((artifact, index) => ({
        id: text(artifact.artifact_id) ?? `${id}-artifact-${index}`,
        label: text(artifact.label) ?? text(artifact.filename) ?? text(artifact.path) ?? 'Artifact',
        kind: text(artifact.kind) ?? text(artifact.mime_type),
        href: sanitizeArtifactHref(artifact.href ?? artifact.uri, artifactAllowedOrigins),
      }));
    const jobEvents = Array.isArray(job.events) ? job.events.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    const tools = [...Object.values(toolCalls), ...jobEvents.filter((event) => text(event.tool_call_id) !== undefined)]
      .filter((tool) => tool.worker_job_id === id)
      .map((tool, index) => ({
        id: text(tool.tool_call_id) ?? `${id}-tool-${index}`,
        label: text(tool.tool_name) ?? text(tool.name) ?? 'Hermes tool',
        status: (tool.status === 'failed' ? 'failed' : tool.status === 'completed' ? 'completed' : 'running') as 'running' | 'completed' | 'failed',
        detail: text(tool.summary) ?? text(tool.message),
      }));
    const jobApprovals = Array.isArray(job.approvals) ? job.approvals.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object')) : [];
    const approval = [...Object.values(approvals), ...jobApprovals].find((item) => (item.worker_job_id === id || jobApprovals.includes(item)) && ['pending', 'resolving'].includes(String(item.state)));
    let progress = number(job.progress);
    if (progress !== undefined && progress <= 1) progress *= 100;
    return {
      id,
      title: text(job.task) ?? text(job.title) ?? 'Delegated work',
      status,
      summary: text(job.summary) ?? text(job.completion),
      progress: progress === undefined ? undefined : Math.max(0, Math.min(100, progress)),
      queuePosition: number(job.queue_position),
      attempt: number(latestAttempt?.attempt_number) ?? (attempts.length || undefined),
      parentAttemptId: text(latestAttempt?.supersedes_attempt_id),
      tools,
      artifacts,
      verification: text(job.verification) ?? text(latestAttempt?.verification),
      approvalMessage: text(approval?.message),
    };
  });
}

export function realtimeReadiness(session: RealtimeSessionController): RealtimePresentationModel['readiness'] {
  switch (session.state) {
    case 'checking':
    case 'connecting_audio': return 'connecting_audio';
    case 'attaching_hermes': return 'attaching_hermes';
    case 'ready': return 'live';
    case 'reconnecting': return 'recovering';
    case 'degraded': return 'degraded';
    case 'blocked': return 'blocked';
    default: return 'disconnected';
  }
}
