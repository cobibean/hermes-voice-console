import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { safeArtifactLink, WorkerJobFeed } from '../components/WorkerJobFeed';
import type { RealtimePresentationModel } from './realtimePresentation';
import { RealtimeStatusBar, RealtimeVoiceControls } from './shared/RealtimeStatusBar';

function presentation(overrides: Partial<RealtimePresentationModel> = {}): RealtimePresentationModel {
  return {
    mode: 'realtime',
    readiness: 'live',
    canReconnect: false,
    muted: false,
    manualTurnTaking: false,
    listening: true,
    speaking: false,
    jobs: [],
    ...overrides,
  };
}

describe('realtime presentation components', () => {
  it('reports authoritative readiness without placing controls in the live region', () => {
    const reconnect = vi.fn();
    const useLegacy = vi.fn();
    const { rerender } = render(<RealtimeStatusBar realtime={presentation()} />);
    const liveStatus = screen.getByRole('status');
    expect(liveStatus).toHaveTextContent('Audio and Hermes control are ready.');
    expect(within(liveStatus).queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Hermes voice activity')).toHaveTextContent('Listening');

    rerender(<RealtimeStatusBar realtime={presentation({
      readiness: 'recovering',
      readinessDetail: 'Rejoining without stopping delegated work.',
      canReconnect: true,
      listening: false,
      onReconnect: reconnect,
      onUseLegacy: useLegacy,
    })} />);
    expect(screen.getByRole('status')).toHaveTextContent('Rejoining without stopping delegated work.');
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect realtime' }));
    expect(reconnect).toHaveBeenCalledOnce();

    rerender(<RealtimeStatusBar realtime={presentation({
      readiness: 'blocked',
      readinessDetail: 'This target does not advertise realtime_voice.',
      canReconnect: true,
      listening: false,
      onUseLegacy: useLegacy,
    })} />);
    expect(screen.queryByRole('button', { name: /Reconnect/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use Legacy turn-based fallback' }));
    expect(useLegacy).toHaveBeenCalledOnce();
  });

  it('labels the fallback explicitly when realtime is absent', () => {
    const fallback = render(<RealtimeStatusBar />);
    expect(within(fallback.container).getByLabelText('Conversation mode')).toHaveTextContent('Legacy turn-based');
    expect(within(fallback.container).getByLabelText('Conversation mode')).toHaveTextContent('Realtime voice is not active');
  });

  it('keeps mute, manual turns, barge-in, and end-call as distinct accessible actions', () => {
    const onMute = vi.fn();
    const onManual = vi.fn();
    const onSend = vi.fn();
    const onInterrupt = vi.fn();
    const onEndCall = vi.fn();
    render(<RealtimeVoiceControls realtime={presentation({
      manualTurnTaking: true,
      manualCaptureState: 'capturing',
      speaking: true,
      onToggleMute: onMute,
      onToggleManualTurnTaking: onManual,
      onSendManualTurn: onSend,
      onDiscardManualTurn: vi.fn(),
      onInterrupt,
      onEndCall,
    })} />);
    const mute = screen.getByRole('button', { name: 'Mute mic' });
    expect(mute).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(mute);
    fireEvent.click(screen.getByRole('button', { name: 'Switch to automatic turns' }));
    fireEvent.click(screen.getByRole('button', { name: 'Send recording' }));
    fireEvent.click(screen.getByRole('button', { name: 'Interrupt Hermes' }));
    fireEvent.click(screen.getByRole('button', { name: 'End call' }));
    expect(onMute).toHaveBeenCalledOnce();
    expect(onManual).toHaveBeenCalledOnce();
    expect(onSend).toHaveBeenCalledOnce();
    expect(onInterrupt).toHaveBeenCalledOnce();
    expect(onEndCall).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Manual recording')).toHaveTextContent('Hermes will not receive this audio until you send it');
    screen.getAllByRole('button').forEach((button) => expect(button).toHaveClass('touch-target'));
  });

  it('provides a keyboard-operable, controller-authoritative two-step manual recording flow', async () => {
    const onStart = vi.fn();
    const onSend = vi.fn();
    const onDiscard = vi.fn();
    const base = presentation({
      manualTurnTaking: true,
      onStartManualTurn: onStart,
      onSendManualTurn: onSend,
      onDiscardManualTurn: onDiscard,
    });
    const manual = render(<RealtimeVoiceControls realtime={{ ...base, manualCaptureState: 'idle' }} />);
    const user = userEvent.setup();
    const start = within(manual.container).getByRole('button', { name: 'Start recording' });
    start.focus();
    await user.keyboard('{Enter}');
    expect(onStart).toHaveBeenCalledOnce();
    expect(within(manual.container).queryByRole('button', { name: /Send recording/ })).not.toBeInTheDocument();

    manual.rerender(<RealtimeVoiceControls realtime={{ ...base, manualCaptureState: 'starting' }} />);
    expect(within(manual.container).getByRole('button', { name: 'Starting recording…' })).toBeDisabled();
    expect(within(manual.container).getByRole('button', { name: 'Starting recording…' })).toHaveAttribute('aria-busy', 'true');

    manual.rerender(<RealtimeVoiceControls realtime={{ ...base, manualCaptureState: 'capturing', listening: true }} />);
    fireEvent.click(within(manual.container).getByRole('button', { name: 'Send recording' }));
    fireEvent.click(within(manual.container).getByRole('button', { name: 'Discard recording' }));
    expect(onSend).toHaveBeenCalledOnce();
    expect(onDiscard).toHaveBeenCalledOnce();
    expect(within(manual.container).getByRole('status')).toHaveTextContent('Hermes will not receive this audio until you send it');

    manual.rerender(<RealtimeVoiceControls realtime={{ ...base, manualCaptureState: 'committing' }} />);
    expect(within(manual.container).getByRole('button', { name: 'Sending recording…' })).toBeDisabled();
    expect(within(manual.container).getByRole('button', { name: 'Discard recording' })).toBeDisabled();
  });

  it('truthfully disables manual recording before authoritative readiness and exposes errors', () => {
    const unavailable = render(<RealtimeVoiceControls realtime={presentation({
      manualTurnTaking: true,
      readiness: 'attaching_hermes',
      manualCaptureState: 'idle',
      onStartManualTurn: vi.fn(),
    })} />);
    expect(within(unavailable.container).getByRole('button', { name: 'Start recording' })).toBeDisabled();
    expect(within(unavailable.container).getByRole('status')).toHaveTextContent('unavailable until audio and Hermes control are ready');

    unavailable.rerender(<RealtimeVoiceControls realtime={presentation({
      manualTurnTaking: true,
      manualCaptureState: 'error',
      manualCaptureError: 'Microphone permission was denied.',
      onStartManualTurn: vi.fn(),
    })} />);
    expect(within(unavailable.container).getByRole('alert')).toHaveTextContent('Microphone permission was denied.');
    expect(within(unavailable.container).getByRole('button', { name: 'Try recording again' })).toBeEnabled();
  });

  it('hides manual capture actions in automatic mode', () => {
    const automatic = render(<RealtimeVoiceControls realtime={presentation({
      manualTurnTaking: false,
      onStartManualTurn: vi.fn(),
      onSendManualTurn: vi.fn(),
    })} />);
    expect(within(automatic.container).queryByLabelText('Manual recording')).not.toBeInTheDocument();
  });

  it('shows queue, progress, lineage, tools, approvals, artifacts, and verification without a worker persona', () => {
    const onStatus = vi.fn();
    const onRefine = vi.fn();
    const onRedirect = vi.fn();
    const onCancel = vi.fn();
    render(<WorkerJobFeed realtime={presentation({
      onRequestStatus: onStatus,
      onRefine,
      onRedirect,
      onCancel,
      jobs: [{
        id: 'job-1',
        title: 'Implement the realtime bridge',
        status: 'awaiting_approval',
        summary: 'Hermes delegated the implementation and is still available here.',
        progress: 64.4,
        queuePosition: 2,
        attempt: 2,
        parentAttemptId: 'attempt-1',
        approvalMessage: 'Allow the deployment command.',
        tools: [{ id: 'tool-1', label: 'Run tests', status: 'completed', detail: '42 passed' }],
        artifacts: [{ id: 'artifact-1', label: 'Verification report', href: '/artifacts/report', kind: 'Document' }],
        verification: 'Focused tests passed.',
      }],
    })} />);

    const card = screen.getByRole('article', { name: 'Implement the realtime bridge' });
    expect(card).toHaveTextContent('Needs approval');
    expect(card).toHaveTextContent('Attempt 2');
    expect(card).toHaveTextContent('Continues attempt attempt-1');
    expect(screen.getByRole('progressbar', { name: 'Implement the realtime bridge progress' })).toHaveAttribute('value', '64');
    expect(within(card).getByLabelText('Tool activity')).toHaveTextContent('42 passed');
    expect(within(card).getByRole('link', { name: 'Verification report' })).toHaveAttribute('href', '/artifacts/report');
    expect(card).toHaveTextContent('Focused tests passed.');
    expect(card).not.toHaveTextContent(/worker persona/i);

    fireEvent.click(within(card).getByRole('button', { name: 'Status' }));
    fireEvent.click(within(card).getByRole('button', { name: 'Refine' }));
    fireEvent.click(within(card).getByRole('button', { name: 'Redirect' }));
    fireEvent.click(within(card).getByRole('button', { name: 'Cancel' }));
    expect(onStatus).toHaveBeenCalledWith('job-1');
    expect(onRefine).toHaveBeenCalledWith('job-1');
    expect(onRedirect).toHaveBeenCalledWith('job-1');
    expect(onCancel).toHaveBeenCalledWith('job-1');
    within(card).getAllByRole('button').forEach((button) => expect(button).toHaveClass('touch-target'));
  });

  it('allows only app artifact routes and explicitly allowlisted HTTPS origins', () => {
    expect(safeArtifactLink('/artifacts/report?id=1')).toEqual({ href: '/artifacts/report?id=1', external: false });
    expect(safeArtifactLink('/api/artifacts/job-1/output')).toEqual({ href: '/api/artifacts/job-1/output', external: false });
    expect(safeArtifactLink('https://files.example.com/report', ['https://files.example.com'])).toEqual({
      href: 'https://files.example.com/report',
      external: true,
    });
    [
      'javascript:alert(1)',
      'data:text/html,bad',
      'file:///tmp/secret',
      '//evil.example/artifacts/report',
      '/report',
      '/artifacts\\..\\secret',
      'https://evil.example/report',
      'https://user:password@files.example.com/report',
      `${window.location.origin}/artifacts/absolute-target-origin`,
    ].forEach((href) => expect(safeArtifactLink(href, ['https://files.example.com'])).toBeNull());
  });

  it('marks external artifact links as a new isolated browsing context', () => {
    render(<WorkerJobFeed realtime={presentation({
      artifactAllowedOrigins: ['https://files.example.com'],
      jobs: [{
        id: 'job-external',
        title: 'External artifact',
        status: 'completed',
        artifacts: [
          { id: 'safe', label: 'Safe external report', href: 'https://files.example.com/report' },
          { id: 'unsafe', label: 'Unsafe report', href: 'javascript:alert(1)' },
        ],
      }],
    })} />);
    const safe = screen.getByRole('link', { name: 'Safe external report' });
    expect(safe).toHaveAttribute('target', '_blank');
    expect(safe).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.queryByRole('link', { name: 'Unsafe report' })).not.toBeInTheDocument();
    expect(screen.getByText('Unsafe report')).toBeInTheDocument();
  });

  it('has a calm empty state and disables unavailable actions', () => {
    const empty = render(<WorkerJobFeed realtime={presentation()} />);
    expect(within(empty.container).getByLabelText('Delegated tasks')).toHaveTextContent('No delegated work yet');
  });
});
