# Diagnostics and agent debugging

The console emits content-free structured lifecycle logs. They make a failed
voice turn reconstructable without logging credentials, prompts, transcripts,
or agent responses.

## Server logs

Set `VOICE_CONSOLE_LOG_LEVEL=DEBUG` for per-25-chunk recording progress. `INFO`
is the default and records socket, recording, STT, Hermes run, recovery, and TTS
boundaries with timing, byte counts, providers, and correlation IDs.

```bash
docker compose logs -f console
docker compose logs console | grep '"turn_id":"vturn_'
docker compose logs console | grep '"run_id":"run_'
```

A healthy voice turn follows this order:

```text
socket.ready
recording.started
recording.stopped
stt.completed
run.submit.requested
coordinator.hermes.accepted
run.submit.accepted
coordinator.terminal
tts.requested
tts.prepared
tts.chunk.synthesized (one or more)
tts.completed
```

Useful interpretations:

- `audio_outside_recording` means the browser sent PCM after its stop command;
  compare `capture.stopped` with `socket.command recording.stop` in browser logs.
- `recording.stopped` with few `pcm_bytes` indicates a capture problem before STT.
- PCM16 mono 16 kHz produces roughly 32,000 bytes per recorded second.
- a long `stt.completed latency_ms` isolates the speech provider from Hermes.
- `coordinator.hermes.accepted` proves Hermes returned a run ID; never resubmit
  it merely because the browser disconnected.
- `coordinator.reconcile.started` means the backend is polling an accepted run,
  not duplicating it.
- `tts.chunk.synthesized` proves provider output exists; missing browser audio
  after that points to transport, MIME, autoplay, or playback behavior.

## Browser logs

Important lifecycle records use the `[hermes-voice-console]` DevTools prefix.
Enable chunk-level records with `?voiceDebug=1` or:

```js
localStorage.setItem('hvc_debug', '1')
```

Disable them with `localStorage.removeItem('hvc_debug')`.

`capture.started` reports actual audio-context rate, track rate, and channels.
`capture.stopped` reports PCM chunks and bytes. Socket records include event
types and turn/run IDs, never event text.

## Privacy contract

Never log authorization headers, tokens, provider or Hermes keys, prompt text,
transcript text, agent output, approval details, or raw audio. Log lengths,
enums, durations, counts, and pseudonymous IDs instead.
