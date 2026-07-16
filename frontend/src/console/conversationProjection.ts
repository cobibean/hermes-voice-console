import type { ConversationMessage } from '../lib/types';
import type { RealtimeEvent, RealtimeSnapshot } from '../lib/realtimeTypes';

export interface RealtimeConversationProjection {
  cursor: string | null;
  seenEventIds: string[];
  messages: ConversationMessage[];
  sessions: Record<string, Record<string, unknown>>;
  toolCalls: Record<string, Record<string, unknown>>;
  approvals: Record<string, Record<string, unknown>>;
  workerJobs: Record<string, Record<string, unknown>>;
  artifacts: Record<string, Record<string, unknown>>;
  listening: boolean;
  speaking: boolean;
}

export const emptyRealtimeProjection: RealtimeConversationProjection = {
  cursor: null,
  seenEventIds: [],
  messages: [],
  sessions: {},
  toolCalls: {},
  approvals: {},
  workerJobs: {},
  artifacts: {},
  listening: false,
  speaking: false,
};

export function sanitizeArtifactHref(value: unknown, allowedOrigins: readonly string[]): string | undefined {
  if (typeof value !== 'string' || value.length > 2_048) return undefined;
  try {
    const url = new URL(value, window.location.origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return undefined;
    if (!allowedOrigins.includes(url.origin)) return undefined;
    if (value.startsWith('/') && !value.startsWith('//') && url.origin === window.location.origin) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
    return url.href;
  } catch {
    return undefined;
  }
}

export function mergeConversationMessages(
  history: ConversationMessage[],
  realtime: ConversationMessage[],
): ConversationMessage[] {
  if (realtime.length === 0) return history;
  const matches = (left: ConversationMessage, right: ConversationMessage) => (
    left.role === right.role && left.content === right.content
  );
  if (realtime.length <= history.length && realtime.every((message, index) => matches(message, history[index]))) {
    return history;
  }
  if (history.length <= realtime.length && history.every((message, index) => matches(message, realtime[index]))) {
    return realtime;
  }
  const maximum = Math.min(history.length, realtime.length);
  let overlap = 0;
  for (let size = maximum; size > 0; size -= 1) {
    if (history.slice(-size).every((message, index) => matches(message, realtime[index]))) {
      overlap = size;
      break;
    }
  }
  return [...history, ...realtime.slice(overlap)];
}

function indexBy(values: unknown, key: string): Record<string, Record<string, unknown>> {
  if (!Array.isArray(values)) return {};
  return Object.fromEntries(values.flatMap((value) => {
    if (!value || typeof value !== 'object') return [];
    const document = value as Record<string, unknown>;
    const id = document[key];
    return typeof id === 'string' ? [[id, document]] : [];
  }));
}

export function projectRealtimeSnapshot(snapshot: RealtimeSnapshot): RealtimeConversationProjection {
  const session = snapshot.session;
  const sessionId = session && typeof session === 'object'
    ? (session as Record<string, unknown>).realtime_session_id
    : null;
  const rawMessages = Array.isArray(snapshot.messages)
    ? snapshot.messages
    : Array.isArray(snapshot.transcript) ? snapshot.transcript : [];
  const messages = rawMessages.filter((value): value is ConversationMessage => {
    if (!value || typeof value !== 'object') return false;
    const message = value as Partial<ConversationMessage>;
    return ['user', 'assistant', 'tool'].includes(message.role ?? '') && typeof message.content === 'string';
  });
  return {
    cursor: snapshot.last_event_id,
    seenEventIds: [],
    messages,
    sessions: typeof sessionId === 'string' ? { [sessionId]: session as Record<string, unknown> } : {},
    toolCalls: indexBy(snapshot.tool_calls, 'tool_call_id'),
    approvals: indexBy(snapshot.pending_approvals ?? snapshot.approvals, 'approval_id'),
    workerJobs: indexBy(snapshot.worker_jobs, 'worker_job_id'),
    artifacts: indexBy(snapshot.artifacts, 'artifact_id'),
    listening: false,
    speaking: false,
  };
}

function payloadId(payload: Record<string, unknown>, key: string): string | null {
  return typeof payload[key] === 'string' ? payload[key] as string : null;
}

/** Pure event reducer. Replayed IDs are ignored and snapshot state remains authoritative. */
export function projectRealtimeEvent(
  current: RealtimeConversationProjection,
  event: RealtimeEvent,
): RealtimeConversationProjection {
  if (current.seenEventIds.includes(event.event_id)) return current;
  const seenEventIds = [...current.seenEventIds, event.event_id].slice(-2_000);
  const next = { ...current, cursor: event.event_id, seenEventIds };
  const payload = event.payload;
  const type = event.type;
  const text = typeof payload.text === 'string'
    ? payload.text
    : typeof payload.content === 'string' ? payload.content
      : typeof payload.transcript === 'string' ? payload.transcript : null;
  if ((type.includes('user.transcript') || type === 'input.accepted') && text) {
    next.messages = [...current.messages, { role: 'user', content: text }];
  } else if ((type.includes('hermes.transcript.completed') || type.includes('assistant.completed')) && text) {
    next.messages = [...current.messages, { role: 'assistant', content: text }];
  }
  if (type === 'speech.started') next.listening = true;
  if (type === 'speech.stopped') next.listening = false;
  if (type === 'hermes.transcript.delta') next.speaking = true;
  if (type === 'response.completed') next.speaking = false;
  const toolId = payloadId(payload, 'tool_call_id');
  if (toolId) {
    const status = type.includes('failed') || payload.ok === false
      ? 'failed' : type.includes('completed') ? 'completed' : payload.status;
    next.toolCalls = { ...current.toolCalls, [toolId]: { ...current.toolCalls[toolId], ...payload, type, ...(status ? { status } : {}) } };
  }
  const approvalId = payloadId(payload, 'approval_id');
  if (approvalId) {
    const state = type.includes('denied') ? 'denied'
      : type.includes('expired') ? 'expired'
        : type.includes('resolved') ? 'resolved' : payload.state;
    next.approvals = { ...current.approvals, [approvalId]: { ...current.approvals[approvalId], ...payload, type, ...(state ? { state } : {}) } };
  }
  const workerId = payloadId(payload, 'worker_job_id');
  if (workerId) next.workerJobs = { ...current.workerJobs, [workerId]: { ...current.workerJobs[workerId], ...payload, type } };
  const artifactId = payloadId(payload, 'artifact_id');
  if (artifactId) next.artifacts = { ...current.artifacts, [artifactId]: { ...current.artifacts[artifactId], ...payload, type } };
  return next;
}
