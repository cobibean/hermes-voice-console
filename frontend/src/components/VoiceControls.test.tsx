import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VoiceControls } from './VoiceControls';

function renderControls(overrides: Partial<Parameters<typeof VoiceControls>[0]> = {}) {
  const props: Parameters<typeof VoiceControls>[0] = {
    recording: 'recording',
    supported: true,
    ready: true,
    speakReplies: true,
    onSpeakReplies: vi.fn(),
    onStart: vi.fn(),
    onStop: vi.fn(),
    onCancelSpeech: vi.fn(),
    inputLevel: 0.4,
    elapsed: 1.2,
    maxSeconds: 120,
    speechFallbackAvailable: false,
    onRetrySpeech: vi.fn(),
    ...overrides,
  };
  render(<VoiceControls {...props} />);
  return props;
}

describe('VoiceControls', () => {
  it('uses one tap to start and a second tap to send', () => {
    const idle = renderControls({ recording: 'idle' });
    fireEvent.click(screen.getByRole('button', { name: 'Start recording' }));
    expect(idle.onStart).toHaveBeenCalledOnce();
    expect(idle.onStop).not.toHaveBeenCalled();
  });

  it('sends the active recording on tap', () => {
    const active = renderControls();
    fireEvent.click(screen.getByRole('button', { name: 'Send recording' }));
    expect(active.onStop).toHaveBeenCalledOnce();
    expect(active.onStart).not.toHaveBeenCalled();
  });

  it('shows a visible user-gesture playback fallback', () => {
    const props = renderControls({ recording: 'idle', speechFallbackAvailable: true });
    fireEvent.click(screen.getByRole('button', { name: 'Play spoken reply' }));
    expect(props.onRetrySpeech).toHaveBeenCalledOnce();
  });
});
