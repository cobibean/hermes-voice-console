import type { RecordingState } from '../lib/state';

export function VoiceControls({
  recording,
  supported,
  speakReplies,
  onSpeakReplies,
  onStart,
  onStop,
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
  onCancelSpeech: () => void;
  inputLevel: number;
  elapsed: number;
  maxSeconds: number;
  speechFallbackAvailable: boolean;
  onRetrySpeech: () => void;
}) {
  const isRecording = recording === 'recording';
  const busy = recording === 'connecting' || recording === 'transcribing';
  return (
    <section className="card controls" aria-label="Voice controls">
      <button
        className={isRecording ? 'mic recording' : 'mic'}
        disabled={!supported || busy}
        onClick={isRecording ? onStop : onStart}
      >
        {isRecording ? 'Send recording' : busy ? 'Working…' : 'Start recording'}
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
