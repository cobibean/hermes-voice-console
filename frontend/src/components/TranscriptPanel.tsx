export function TranscriptPanel({ transcript, response }: { transcript: string; response: string }) {
  return (
    <section className="card">
      <h2>Transcript</h2>
      <p className="transcript">{transcript || 'No transcript yet.'}</p>
      <h2>Assistant response</h2>
      <p className="response">{response || 'No response yet.'}</p>
    </section>
  );
}
