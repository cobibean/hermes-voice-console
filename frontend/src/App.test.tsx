import { render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

vi.mock('@clerk/react', () => ({
  ClerkProvider: ({ children }: { children: ReactNode }) => children,
  Show: ({ when, children }: { when: string; children: ReactNode }) =>
    when === 'signed-out' ? children : null,
  SignInButton: ({ children }: { children: ReactNode }) => children,
  SignUpButton: ({ children }: { children: ReactNode }) => children,
  UserButton: () => <button>Account</button>,
  useAuth: () => ({ getToken: vi.fn(async () => 'clerk-token') }),
}));

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('App authentication modes', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders service mode as programmatic-only with no secret input', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      auth_mode: 'service',
      clerk_publishable_key: null,
      public_base_url: 'https://console.example.test',
    })));
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Programmatic access only' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/token|secret/i)).not.toBeInTheDocument();
  });

  it('renders loopback development mode with a prominent warning and no credential', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === '/api/public-config') {
        return jsonResponse({
          auth_mode: 'development',
          clerk_publishable_key: null,
          public_base_url: 'http://localhost:8787',
        });
      }
      return jsonResponse({
        server: { public_base_url: 'http://localhost:8787', auth_mode: 'development' },
        principal: { kind: 'development', owner_key: 'owner-key' },
        voice: {
          stt_provider: 'fake',
          tts_provider: 'fake',
          sample_rate: 16000,
          max_recording_seconds: 120,
          speak_replies_default: false,
        },
        targets: [],
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem');
    render(<App />);
    expect(await screen.findByText(/development authentication is active/i)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/bootstrap', expect.anything()));
    expect(storageSpy).not.toHaveBeenCalled();
    storageSpy.mockRestore();
  });

  it('renders Clerk sign-in controls from runtime public config', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      auth_mode: 'clerk',
      clerk_publishable_key: 'pk_test_public',
      public_base_url: 'https://console.example.test',
    })));
    render(<App />);
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument();
  });
});
