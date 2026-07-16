import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WorkerJobFeed } from '../components/WorkerJobFeed';
import type { RealtimePresentationModel } from './realtimePresentation';
import { RealtimeStatusBar, RealtimeVoiceControls } from './shared/RealtimeStatusBar';

function presentation(overrides: Partial<RealtimePresentationModel> = {}): RealtimePresentationModel {
  return {
    mode: 'realtime',
    connection: 'live',
    muted: false,
    manualTurnTaking: false,
    listening: true,
    speaking: false,
    jobs: [],
    ...overrides,
  };
}

describe('realtime presentation components', () => {
  it('makes realtime connection and voice state understandable', () => {
    const reconnect = vi.fn();
    const { rerender } = render(<RealtimeStatusBar realtime={presentation()} />);
    expect(screen.getByRole('status')).toHaveTextContent('Realtime');
    expect(screen.getByLabelText('Hermes voice activity')).toHaveTextContent('Listening');

    rerender(<RealtimeStatusBar realtime={presentation({
      connection: 'recovering',
      connectionDetail: 'Rejoining without stopping delegated work.',
      listening: false,
    })} />);
    expect(screen.getByRole('status')).toHaveTextContent('Rejoining without stopping delegated work.');

    rerender(<RealtimeStatusBar realtime={presentation({
      connection: 'blocked',
      connectionDetail: 'This target does not advertise realtime_voice.',
      listening: false,
      onReconnect: reconnect,
    })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
    expect(reconnect).toHaveBeenCalledOnce();
  });

  it('labels the fallback explicitly when realtime is absent', () => {
    const fallback = render(<RealtimeStatusBar />);
    expect(within(fallback.container).getByLabelText('Conversation mode')).toHaveTextContent('Legacy turn-based');
    expect(within(fallback.container).getByLabelText('Conversation mode')).toHaveTextContent('Realtime voice is not active');
  });

  it('provides accessible local mute, manual turn, and barge-in controls', () => {
    const onMute = vi.fn();
    const onManual = vi.fn();
    const onInterrupt = vi.fn();
    render(<RealtimeVoiceControls realtime={presentation({
      speaking: true,
      onToggleMute: onMute,
      onToggleManualTurnTaking: onManual,
      onInterrupt,
    })} />);
    const mute = screen.getByRole('button', { name: 'Mute mic' });
    expect(mute).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(mute);
    fireEvent.click(screen.getByRole('button', { name: 'Automatic turns' }));
    fireEvent.click(screen.getByRole('button', { name: 'Interrupt Hermes' }));
    expect(onMute).toHaveBeenCalledOnce();
    expect(onManual).toHaveBeenCalledOnce();
    expect(onInterrupt).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Realtime voice controls')).toHaveTextContent('keeps delegated work running');
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
        artifacts: [{ id: 'artifact-1', label: 'Verification report', href: '/report', kind: 'Document' }],
        verification: 'Focused tests passed.',
      }],
    })} />);

    const card = screen.getByRole('article', { name: 'Implement the realtime bridge' });
    expect(card).toHaveTextContent('Needs approval');
    expect(card).toHaveTextContent('Attempt 2');
    expect(card).toHaveTextContent('Continues attempt attempt-1');
    expect(screen.getByRole('progressbar', { name: 'Implement the realtime bridge progress' })).toHaveAttribute('value', '64');
    expect(within(card).getByLabelText('Tool activity')).toHaveTextContent('42 passed');
    expect(within(card).getByRole('link', { name: 'Verification report' })).toHaveAttribute('href', '/report');
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
  });

  it('has a calm empty state and disables unavailable actions', () => {
    const empty = render(<WorkerJobFeed realtime={presentation()} />);
    expect(within(empty.container).getByLabelText('Delegated tasks')).toHaveTextContent('No delegated work yet');
  });
});
