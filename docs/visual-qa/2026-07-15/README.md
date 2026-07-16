# Hermes Voice Console visual QA — 2026-07-15

## Direction

The final UI uses a distinct Nous/Hermes-inspired research-console language without copying the product page: graphite-black technical grid, ivory editorial display type, electric cyan and ultraviolet signaling, monospaced operational microcopy, thin keylines, and generous negative space.

Product hierarchy remains the priority:

- Hermes is the only visible persona.
- Realtime conversation status stays above the workspace.
- Delegated work appears inside the conversation workspace, never as a second chat persona.
- Approval is a focused, server-authoritative interruption.
- Mobile keeps the composer and voice control reachable with 44px minimum targets.

## Evidence

Every final image is a viewport capture, not a full-page capture. This matters for fixed composer, voice-control, and modal placement. The PNG dimensions exactly match the browser viewport used for the scenario.

| Capture | Viewport | State truth |
| --- | ---: | --- |
| `final/desktop-initial.png` | 1440×1000 | Real local legacy fixture |
| `final/mobile-initial.png` | 390×844 | Real local legacy fixture |
| `final/landscape-mobile-initial.png` | 844×390 | Real local legacy fixture |
| `final/desktop-realtime-approval-worker.png` | 1440×1000 | Real local fake-contract Realtime approval and worker state; deterministic browser media peer |
| `final/desktop-realtime-live-worker.png` | 1440×1200 | Real local fake-contract active worker; approval layer hidden to inspect the underlying workspace |
| `final/desktop-realtime-live-conversation.png` | 1440×1300 | Deterministic conversation projection on the real Realtime shell |
| `final/desktop-realtime-completed-artifact.png` | 1440×1400 | Deterministic terminal job/artifact projection on the real Realtime shell |
| `final/desktop-realtime-soul-workspace-delegation.png` | 1440×1000 | Live disposable GPT-Realtime-2.1 acceptance: profile `SOUL.md` read and Voice Console workspace binding |
| `final/desktop-realtime-completed-soul-worker.png` | 1440×1000 | Live disposable acceptance: one GPT-5.6 read-only worker completed and its result was spoken |
| `final/desktop-realtime-recovery.png` | 1440×900 | Real failed-peer recovery state |
| `final/mobile-realtime-approval.png` | 390×844 | Real local fake-contract approval state; deterministic browser media peer |
| `final/mobile-realtime-manual-capture.png` | 390×844 | Production controls with the fake target turn-mode endpoint |

Reference:

- `nous-hermes-reference.png` — official Hermes Agent page captured during the visual-language review. Remote page assets rendered incompletely in headless Chromium, so it was treated as directional evidence rather than a pixel target.

The Realtime approval capture uses the real local fake-contract state and production presentation components. Only the browser media peer is replaced with a deterministic in-page peer because the local fake target intentionally returns non-media SDP.

The live-conversation and completed-artifact captures are visual projection fixtures layered onto that same real Realtime shell. Their copy and terminal job state are deterministic presentation data, not evidence that the fake target performed the described release audit. The table above is the source of truth for screenshot provenance.

The `soul-workspace-delegation` and `completed-soul-worker` captures are different: they come from the isolated local Hermes staging profile at `http://localhost:18787`. They show a real profile-document tool call, real repository workspace search, and a completed `gpt-5.6-sol` worker run with no file writes.
