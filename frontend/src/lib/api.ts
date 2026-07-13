import type { Bootstrap, PublicConfig, SessionInfo } from './types';

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
