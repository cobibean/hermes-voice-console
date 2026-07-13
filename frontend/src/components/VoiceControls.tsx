import { useRef } from 'react';
import type { RecordingState } from '../lib/state';

export function VoiceControls({
  recording,
  supported,
  speakReplies,
  onSpeakReplies,
  onStart,
  onStop,
  onDiscard,
  onCancelSpeech,
  inputLevel,
  elapsed,
  maxSeconds,
  speechFallbackAvailable,
  onRetrySpeech,
}: {
  recording: RecordingState;
  supported: boolean;
  speakReplies: boolean;
  onSpeakReplies: (value: boolean) => void;
  onStart: () => void;
  onStop: () => void;
  onDiscard: () => void;
  onCancelSpeech: () => void;
  inputLevel: number;
  elapsed: number;
  maxSeconds: number;
  speechFallbackAvailable: boolean;
  onRetrySpeech: () => void;
}) {
  const activePointer = useRef<number | null>(null);
  const isRecording = recording === 'recording';
  const busy = recording === 'connecting' || recording === 'transcribing';
  return (
    <section className="card controls" aria-label="Voice controls">
      <button
        className={isRecording ? 'mic recording' : 'mic'}
        disabled={!supported || busy}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          activePointer.current = event.pointerId;
          if (!isRecording) onStart();
        }}
        onPointerUp={(event) => {
          if (activePointer.current !== event.pointerId) return;
          activePointer.current = null;
          onStop();
        }}
        onPointerCancel={(event) => {
          if (activePointer.current !== event.pointerId) return;
          activePointer.current = null;
          onDiscard();
        }}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          if (!event.repeat && !isRecording) onStart();
        }}
        onKeyUp={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onStop();
          }
        }}
      >
        {isRecording ? 'Release to send' : busy ? 'Working…' : 'Hold to talk'}
      </button>
      <div className="input-meter" aria-hidden="true"><span style={{ transform: `scaleX(${inputLevel})` }} /></div>
      <output className="recording-time" aria-label="Recording time">
        {isRecording ? `${elapsed.toFixed(1)} / ${maxSeconds}s` : 'Ready'}
      </output>
      <button type="button" onClick={onCancelSpeech}>Cancel speech</button>
      {speechFallbackAvailable ? <button className="speech-fallback" type="button" onClick={onRetrySpeech}>Play spoken reply</button> : null}
      <label className="toggle"><input type="checkbox" checked={speakReplies} onChange={(event) => onSpeakReplies(event.target.checked)} /> Speak replies</label>
      <p className="ai-voice-disclosure">Spoken replies use an AI-generated voice.</p>
      {!supported ? <p className="warning">Browser mic capture needs localhost/HTTPS and AudioWorklet support.</p> : null}
    </section>
  );
}
