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

Baseline:

- `baseline/desktop-initial.png`
- `baseline/mobile-initial.png`

Final:

- `final/desktop-initial.png`
- `final/mobile-initial.png`
- `final/landscape-mobile-initial.png`
- `final/desktop-realtime-approval-worker.png`
- `final/desktop-realtime-live-worker.png`
- `final/desktop-realtime-live-conversation.png`
- `final/desktop-realtime-completed-artifact.png`
- `final/desktop-realtime-recovery.png`
- `final/mobile-realtime-approval.png`
- `final/mobile-realtime-manual-capture.png`

Reference:

- `nous-hermes-reference.png` — official Hermes Agent page captured during the visual-language review. Remote page assets rendered incompletely in headless Chromium, so it was treated as directional evidence rather than a pixel target.

The Realtime approval capture uses the real local fake-contract state and production presentation components. Only the browser media peer is replaced with a deterministic in-page peer because the local fake target intentionally returns non-media SDP.

The live-conversation and completed-artifact captures are visual projection fixtures layered onto that same real Realtime shell. Their copy and terminal job state are deterministic presentation data, not evidence that the fake target performed the described release audit. The recovery capture is a real failed-peer state; the manual-capture image uses the production controls and fake target turn-mode endpoint.
