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
| `DELETE` | `/api/realtime/sessions/{session_id}` | `target` |
| `POST` | `/api/realtime/sessions/{session_id}/activate` | `target`; `{session_generation, client_request_id}` |
| `POST` | `/api/realtime/sessions/{session_id}/input` | `target`; `{session_generation, client_request_id, text}` |
| `POST` | `/api/realtime/sessions/{session_id}/interrupt` | `target`; `{session_generation, client_request_id}` |
| `GET` | `/api/realtime/sessions/{session_id}/events` | `target`, optional opaque `after` |
| `POST` | `/api/realtime/sessions/{session_id}/approvals/{approval_id}` | `target`; `{session_generation, client_request_id, choice}` |
| `GET` | `/api/realtime/conversations/{conversation_id}` | `target` |
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

Errors use `{error: {code, message}}`. Provider and target exception text is never reflected.
Request bodies, SDP, response documents, cursor lengths, and target request durations are bounded.
