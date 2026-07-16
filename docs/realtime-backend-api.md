# Voice Console Realtime Backend API

This API is an authenticated, owner-scoped proxy to a target Hermes API Server. It is disabled
per target by default. Set `realtime_enabled: true` only for a target that passes the strict
`contracts.realtime` 1.x compatibility preflight.

The browser receives neither the Hermes API credential nor an OpenAI credential. The backend
derives the provider safety identifier from the authenticated conversation owner and ignores any
browser-provided value.

## Browser routes

All routes require normal Voice Console authentication. `target` is a query parameter except on
session creation, where it is a JSON field.

| Method | Route | Request or cursor |
| --- | --- | --- |
| `GET` | `/api/realtime/targets/{target}/compatibility` | None |
| `POST` | `/api/realtime/sessions` | `{target, conversation_id, client_request_id, sdp_offer, turn_mode?}` |
| `GET` | `/api/realtime/sessions/{session_id}` | `target` |
| `DELETE` | `/api/realtime/sessions/{session_id}` | `target`; JSON `{client_request_id}` |
| `POST` | `/api/realtime/sessions/{session_id}/activate` | `target`; `{session_generation, client_request_id}` |
| `POST` | `/api/realtime/sessions/{session_id}/input` | `target`; `{session_generation, client_request_id, text}` |
| `POST` | `/api/realtime/sessions/{session_id}/interrupt` | `target`; `{session_generation, client_request_id}` |
| `GET` | `/api/realtime/sessions/{session_id}/events` | `target`, optional opaque `after` |
| `POST` | `/api/realtime/sessions/{session_id}/approvals/{approval_id}` | `target`; `{session_generation, client_request_id, choice}` |
| `GET` | `/api/realtime/conversations/{conversation_id}` | `target` |
| `GET` | `/api/realtime/conversations/{conversation_id}/requests/{client_request_id}` | `target` |
| `GET` | `/api/realtime/conversations/{conversation_id}/worker-jobs` | `target` |
| `GET` | `/api/realtime/conversations/{conversation_id}/worker-jobs/{job_id}` | `target` |
| `GET` | `/api/realtime/conversations/{conversation_id}/worker-jobs/{job_id}/events` | `target`, integer `after` |
| `POST` | `/api/realtime/conversations/{conversation_id}/worker-jobs/{job_id}/{refine\|redirect\|cancel}` | `target`; `{command_id, expected_revision, payload}` |

The create response contains `answer_sdp`, opaque `realtime_session_id`,
`session_generation`, `conversation_id`, and lifecycle `state`. Hermes remains authoritative for
conversation snapshots, events, approvals, worker jobs, and command acknowledgements.

Event replay returns `{conversation_id, events, last_event_id}`. A cursor outside retained history
returns HTTP 409 with `error.code = event_replay_gap`; the client must load the conversation
snapshot and resume from its authoritative cursor.

Every session mutation carries a bounded `client_request_id`. Hermes echoes the original result for
an exact duplicate and exposes durable acceptance through the request-result route. A mutation whose
outcome cannot be proven returns HTTP 202 with
`{client_request_id, operation, state: "outcome_unknown", accepted: false}`; the console never
blindly repeats it. The proxy derives and forwards the durable `conversation_id` for every
post-create Hermes mutation rather than trusting a browser-provided value.

Errors use `{error: {code, message}}`. Provider and target exception text is never reflected.
Request bodies, SDP, response documents, cursor lengths, and target request durations are bounded.

`/ws/realtime` is the dedicated authenticated control channel. Its first post-authentication frame
must be `{type: "subscribe", target, conversation_id, realtime_session_id, after?}`. It sends an
authoritative snapshot before replay events and accepts bounded `input`, `interrupt`, `approval`,
and `worker.command` frames. Heartbeats, send deadlines, replay-gap snapshots, and a slow-consumer
close policy keep this channel independent from the legacy `/ws/voice` state machine.
