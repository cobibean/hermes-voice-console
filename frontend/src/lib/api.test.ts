import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadSessionMessages } from './api';

describe('conversation history API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads owned Hermes messages for the selected target and conversation', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      messages: [
        { role: 'user', content: 'first turn' },
        { role: 'assistant', content: 'first reply' },
      ],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    const messages = await loadSessionMessages('hvc_123', 'job-hunter', async () => 'clerk-token');
    expect(messages).toHaveLength(2);
    expect(fetch).toHaveBeenCalledWith(
      '/api/sessions/hvc_123/messages?target=job-hunter',
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
    const headers = fetch.mock.calls[0][1].headers as Headers;
    expect(headers.get('Authorization')).toBe('Bearer clerk-token');
  });
});
