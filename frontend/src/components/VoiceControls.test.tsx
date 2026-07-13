import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { VoiceControls } from './VoiceControls';

function renderControls(overrides: Partial<Parameters<typeof VoiceControls>[0]> = {}) {
  const props: Parameters<typeof VoiceControls>[0] = {
    recording: 'recording',
    supported: true,
    speakReplies: true,
    onSpeakReplies: vi.fn(),
    onStart: vi.fn(),
    onStop: vi.fn(),
    onDiscard: vi.fn(),
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
  it('discards rather than submits an interrupted pointer gesture', () => {
    HTMLElement.prototype.setPointerCapture = vi.fn();
    const props = renderControls();
    const mic = screen.getByRole('button', { name: 'Release to send' });
    fireEvent.pointerDown(mic, { pointerId: 7 });
    fireEvent.pointerCancel(mic, { pointerId: 7 });
    expect(props.onDiscard).toHaveBeenCalledOnce();
    expect(props.onStop).not.toHaveBeenCalled();
  });

  it('shows a visible user-gesture playback fallback', () => {
    const props = renderControls({ recording: 'idle', speechFallbackAvailable: true });
    fireEvent.click(screen.getByRole('button', { name: 'Play spoken reply' }));
    expect(props.onRetrySpeech).toHaveBeenCalledOnce();
  });
});
