import { act, fireEvent, render, screen } from '@testing-library/react';
import { useRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { initialConsoleState } from '../lib/state';
import { DesktopConsole } from './DesktopConsole';
import { MobileConsole } from './MobileConsole';
import type { ConsoleController } from './useConsoleController';
import { useConsoleLayout } from './useConsoleLayout';
import { deriveConsoleViewState } from './viewState';

function LayoutHarness() {
  const layout = useConsoleLayout();
  const controllerIdentity = useRef('shared-controller');
  const [turns, setTurns] = useState(0);

  return (
    <main data-console-shell={layout}>
      <span>{controllerIdentity.current}</span>
      <span data-testid="turns">{turns}</span>
      <button onClick={() => setTurns((value) => value + 1)}>Increment</button>
    </main>
  );
}

describe('console architecture seams', () => {
  const controller = {
    acceptanceUnknown: null,
    acknowledgeAcceptanceUnknown: vi.fn(),
    approval: null,
    bootstrap: {
      server: { public_base_url: 'http://localhost:8787', auth_mode: 'development' },
      principal: { kind: 'development', owner_key: 'owner' },
      voice: { stt_provider: 'fake', tts_provider: 'fake', sample_rate: 16000, max_recording_seconds: 120, speak_replies_default: false },
      targets: [{ name: 'fake', label: 'Fake agent', preferred_transport: 'runs', api_key_configured: true }],
    },
    cancelSpeech: vi.fn(),
    closeClient: vi.fn(),
    connect: vi.fn(),
    connected: true,
    isCaptureSupported: true,
    loadError: undefined,
    newConversation: vi.fn(),
    response: 'Agent response',
    resolveApproval: vi.fn(),
    selectSession: vi.fn(),
    selectTarget: vi.fn(),
    selectedTarget: 'fake',
    sessionKey: 'hvc_1',
    sessions: [{ conversation_id: 'hvc_1', target: 'fake', title: 'Conversation', created_at: 1, updated_at: 1 }],
    setSpeakReplies: vi.fn(),
    setTextDraft: vi.fn(),
    speakReplies: false,
    startRecording: vi.fn(),
    state: initialConsoleState,
    stopRecording: vi.fn(),
    stopRun: vi.fn(),
    submitText: vi.fn(),
    textDraft: '',
    timeline: [],
    transcript: 'User message',
    viewState: 'ready',
  } as unknown as ConsoleController;

  it('derives one explicit visual state from transport state', () => {
    expect(deriveConsoleViewState(initialConsoleState, false)).toBe('disconnected');
    expect(deriveConsoleViewState(initialConsoleState, true)).toBe('ready');
    expect(
      deriveConsoleViewState({ ...initialConsoleState, recording: 'recording' }, true),
    ).toBe('listening');
    expect(
      deriveConsoleViewState({ ...initialConsoleState, agent: 'waiting_for_approval' }, true),
    ).toBe('waiting_for_approval');
    expect(
      deriveConsoleViewState({ ...initialConsoleState, error: 'broken' }, true),
    ).toBe('failed');
  });

  it('switches one mounted shell without resetting controller state', () => {
    let matches = false;
    const listeners = new Set<() => void>();
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      get matches() {
        return matches;
      },
      media: '',
      onchange: null,
      addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));

    const { container } = render(<LayoutHarness />);
    expect(container.querySelectorAll('[data-console-shell]')).toHaveLength(1);
    expect(container.querySelector('[data-console-shell="desktop"]')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Increment' }));
    expect(screen.getByTestId('turns')).toHaveTextContent('1');

    act(() => {
      matches = true;
      listeners.forEach((listener) => listener());
    });

    expect(container.querySelectorAll('[data-console-shell]')).toHaveLength(1);
    expect(container.querySelector('[data-console-shell="mobile"]')).toBeInTheDocument();
    expect(screen.getByText('shared-controller')).toBeInTheDocument();
    expect(screen.getByTestId('turns')).toHaveTextContent('1');
    vi.unstubAllGlobals();
  });

  it('renders intentionally different desktop and mobile information architecture', () => {
    const desktop = render(<DesktopConsole controller={controller} />);
    expect(screen.getByRole('complementary', { name: 'Conversations' })).toBeInTheDocument();
    expect(screen.getByTestId('run-inspector')).toBeInTheDocument();
    desktop.unmount();

    render(<MobileConsole controller={controller} />);
    expect(screen.getByText('Agent and conversation')).toBeInTheDocument();
    expect(screen.getByText('Activity and diagnostics')).toBeInTheDocument();
    expect(screen.getByLabelText('Message composer')).toHaveClass('composer-mobile');
  });
});
