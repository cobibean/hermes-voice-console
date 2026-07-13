# Hermes Voice Console Phase 8 Memory - 2026-07-12

## Session summary

Closed Phase 8 of the V1 implementation plan. The deployed JobHunter console now completes a real browser microphone -> OpenAI STT -> Hermes run -> OpenAI TTS -> browser playback loop on both Mac and phone. Conversation history reloads from Hermes, recording uses a two-tap toggle, mobile capture was hardened, and content-safe structured diagnostics are available for future humans and agents.

## Decisions made

- OpenAI STT defaults to `gpt-4o-mini-transcribe`; `whisper-1` remains configurable.
- The JobHunter deployment uses OpenAI STT and OpenAI TTS with an owner-provided API credential stored only in the mode-0600 deployment environment.
- JobHunter provides the optional `en` STT language hint; the open-source default remains automatic language detection.
- Both shells use **Start recording -> Send recording**. This user-approved direction replaces the earlier hold-to-talk / pointer-capture plan.
- Conversation presentation is a persistent user/assistant message stream loaded from the existing owned-session history endpoint.
- Speech cancellation stays separate from Hermes run cancellation. TTS errors and autoplay failures leave text available.
- Diagnostics log metadata, timings, byte counts, providers, and correlation IDs, never credentials, raw audio, transcripts, prompts, approval details, or agent output.

## What changed

- Added silence/short-audio and known hallucination filtering before Hermes submission.
- Added sentence-level TTS preparation, markdown and think stripping, per-chunk timeouts, MIME propagation, `(turn_id, chunk_index)` framing, sequential playback, stale rejection, cancellation, and an autoplay fallback.
- Added measured microphone level, elapsed/max recording time, AI voice disclosure, safe-area/dynamic viewport styling, forced-colors and reduced-motion support, visible focus, semantic announcements, and page-hide/pageshow recovery.
- Fixed the browser stop race by shutting capture down before sending `recording.stop`; post-stop PCM no longer reaches the server.
- Replaced point-sampled downsampling with window averaging for cleaner 44.1/48 kHz mobile input.
- Added frontend history loading and conversation rendering from `/api/sessions/{conversation_id}/messages`.
- Added structured server/browser lifecycle diagnostics and `docs/diagnostics.md`.
- Updated the source-of-truth plan and design docs to record the two-tap interaction decision.

## Verification

- Local provider proof transcribed generated speech accurately with `gpt-4o-mini-transcribe` and returned valid MPEG audio from `gpt-4o-mini-tts`.
- Full local check at the final Phase 8 revision: Ruff passed; 42 backend tests passed; 9 frontend files / 25 tests passed; frontend lint, typecheck, production build, and fake protocol E2E passed.
- Live revision/image: `b396e23` / `hermes-voice-console:b396e23`.
- Live container: healthy, zero restarts; console remains loopback-only on 8788 and Hermes remains loopback-only on 8642 behind the existing surgical Tailscale Serve endpoint.
- Deployed real-audio proof passed STT, a real JobHunter Hermes run, TTS, and session-history reload. Hermes returned two persisted roles (`user`, `assistant`).
- No `audio_outside_recording` events occurred after the stop-order fix.
- Structured production logs emitted the expected capture/STT/run/TTS lifecycle with timings and byte counts.
- User verified Mac speech input and spoken replies, then verified the final history, two-tap recording, and phone transcription fixes worked perfectly.

## Gotchas and constraints

- Do not log or commit the configured OpenAI credential.
- Browser audio diagnostics can be expanded temporarily with `?voiceDebug=1` or `localStorage.setItem('hvc_debug', '1')`; remove the setting after investigation.
- A normal PCM16 mono 16 kHz recording is approximately 32,000 bytes per second. This is a useful first check for mobile capture failures.
- Existing Hermes smart-approval behavior from Phase 7 remains: an approval may be resolved upstream before the console sees it.
- Tailscale Serve must still be modified surgically; never use `tailscale serve reset` on JobHunter.

## Source of truth

- `docs/plans/2026-07-12-portable-hermes-voice-console-v1-implementation-plan.md`
- `docs/diagnostics.md`

## Recommended next work

- Phase 9: add deterministic browser acceptance coverage for both shells, viewports, recovery, accessibility, mobile backgrounding/rotation, approvals, and no-duplicate submission behavior.
