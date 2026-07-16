import type { Bootstrap, ConversationMessage, PublicConfig, SessionInfo } from './types';
import type { RealtimeCompatibility, RealtimeSessionDocument, RealtimeTurnMode } from './realtimeTypes';

export type AuthTokenProvider = (skipCache?: boolean) => Promise<string | null>;

export async function loadPublicConfig(): Promise<PublicConfig> {
  const response = await fetch('/api/public-config');
  if (!response.ok) throw new Error(`Unable to load console configuration (${response.status})`);
  return (await response.json()) as PublicConfig;
}

export async function apiFetch<T>(
  path: string,
  getToken: AuthTokenProvider,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  const token = await getToken(false);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(
      `${response.status} ${response.statusText}${body ? `: ${body.slice(0, 200)}` : ''}`,
    );
  }
  return (await response.json()) as T;
}

export async function loadBootstrap(getToken: AuthTokenProvider): Promise<Bootstrap> {
  return apiFetch<Bootstrap>('/api/bootstrap', getToken);
}

export async function listSessions(
  target: string,
  getToken: AuthTokenProvider,
): Promise<SessionInfo[]> {
  const result = await apiFetch<{ sessions: SessionInfo[] }>(
    `/api/sessions?target=${encodeURIComponent(target)}`,
    getToken,
  );
  return result.sessions;
}

export async function createSession(
  target: string,
  getToken: AuthTokenProvider,
): Promise<SessionInfo> {
  return apiFetch<SessionInfo>('/api/sessions', getToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
}

export async function loadSessionMessages(
  conversationId: string,
  target: string,
  getToken: AuthTokenProvider,
): Promise<ConversationMessage[]> {
  const result = await apiFetch<{ messages: ConversationMessage[] }>(
    `/api/sessions/${encodeURIComponent(conversationId)}/messages?target=${encodeURIComponent(target)}`,
    getToken,
  );
  return result.messages;
}

export async function loadRealtimeCompatibility(
  target: string,
  getToken: AuthTokenProvider,
): Promise<RealtimeCompatibility> {
  return apiFetch<RealtimeCompatibility>(
    `/api/realtime/targets/${encodeURIComponent(target)}/compatibility`,
    getToken,
  );
}

export async function createRealtimeSession(
  input: {
    target: string;
    conversationId: string;
    sdpOffer: string;
    clientRequestId: string;
    turnMode: RealtimeTurnMode;
  },
  getToken: AuthTokenProvider,
): Promise<RealtimeSessionDocument> {
  return apiFetch<RealtimeSessionDocument>('/api/realtime/sessions', getToken, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target: input.target,
      conversation_id: input.conversationId,
      sdp_offer: input.sdpOffer,
      client_request_id: input.clientRequestId,
      turn_mode: input.turnMode,
    }),
  });
}

export async function activateRealtimeSession(
  input: { target: string; sessionId: string; sessionGeneration: number; clientRequestId: string },
  getToken: AuthTokenProvider,
): Promise<void> {
  await apiFetch<Record<string, unknown>>(
    `/api/realtime/sessions/${encodeURIComponent(input.sessionId)}/activate?target=${encodeURIComponent(input.target)}`,
    getToken,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_request_id: input.clientRequestId,
        session_generation: input.sessionGeneration,
      }),
    },
  );
}

export async function closeRealtimeSession(
  input: { target: string; sessionId: string; clientRequestId: string },
  getToken: AuthTokenProvider,
): Promise<void> {
  await apiFetch<Record<string, unknown>>(
    `/api/realtime/sessions/${encodeURIComponent(input.sessionId)}?target=${encodeURIComponent(input.target)}`,
    getToken,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_request_id: input.clientRequestId }),
    },
  );
}
