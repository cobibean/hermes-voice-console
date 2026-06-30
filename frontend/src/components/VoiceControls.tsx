import type { RecordingState } from '../lib/state';

export function VoiceControls({
  recording,
  supported,
  speakReplies,
  onSpeakReplies,
  onStart,
  onStop,
  onCancelSpeech,
}: {
  recording: RecordingState;
  supported: boolean;
  speakReplies: boolean;
  onSpeakReplies: (value: boolean) => void;
  onStart: () => void;
  onStop: () => void;
  onCancelSpeech: () => void;
}) {
  const isRecording = recording === 'recording';
  const busy = recording === 'connecting' || recording === 'transcribing';
  return (
    <section className="card controls" aria-label="Voice controls">
      <button
        className={isRecording ? 'mic recording' : 'mic'}
        disabled={!supported || busy}
        onPointerDown={() => { if (!isRecording) onStart(); }}
        onPointerUp={onStop}
        onPointerLeave={onStop}
      >
        {isRecording ? 'Release to send' : busy ? 'Working…' : 'Hold to talk'}
      </button>
      <button type="button" onClick={onCancelSpeech}>Cancel speech</button>
      <label className="toggle"><input type="checkbox" checked={speakReplies} onChange={(event) => onSpeakReplies(event.target.checked)} /> Speak replies</label>
      {!supported ? <p className="warning">Browser mic capture needs localhost/HTTPS and AudioWorklet support.</p> : null}
    </section>
  );
}
