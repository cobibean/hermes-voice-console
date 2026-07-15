# Phase 2-3 Hermes Runtime Memory

**Date:** 2026-07-15

**Status:** Phase 2 and Phase 3 gates passed

## Pinned upstream commits

- Phase 1 proof: `cadd93e6a0cddbd29c9b66abe85c862eeb4e4ffa`
- Durable worker-job foundation: `412b551`
- Worker-job semantics remediation: `181dfc2`
- Transport-neutral Realtime execution runtime: `d6891b2`
- Worker lifecycle remediation: `98a8cdc`
- Redirected-attempt projection remediation and verified head: `63f4c9024e7a88566703d9081690aaea9f26c19e`

## Phase 2 outcome

- The configured API runtime now uses a per-conversation `AgentExecutionContext` rather than a proof callback or private delegation dispatch path.
- Native Hermes approvals suspend the tool call and return the final approved, denied, or failed result to Realtime exactly once within the live process.
- Realtime tool schemas are normalized and raw `delegate_task` remains behind the `delegate_work` policy boundary.
- Provider event parsing, replay gaps, context size, retention, cleanup, timeouts, agent reuse, and default logging are bounded or fail closed.
- Duplicate provider calls and partial provider writes resume by delivery stage without duplicating tool execution, function output, or response continuation.

Independent Phase 2 evidence: 46 focused tests, 170 broad regressions, Ruff, compilation, diff checks, broker/approval adversarial probes, and the live GPT-Realtime/GPT-5.6 proof passed.

## Phase 3 outcome

- Logical worker jobs reuse Hermes async delegation and own stable job, attempt, command, delivery, artifact, approval, and event identities.
- One `gpt-5.6-sol` lead is the default; model and fan-out validation happen before child allocation.
- FIFO, cancellation, refinement, redirect, attempt lineage, process-loss classification, and command acknowledgements are owner-bound and truthful.
- Browser, session, and Realtime-call teardown do not interrupt routable work. Explicit worker cancellation still does.
- Original and redirected attempts project real progress, tool activity, approvals, artifacts, verification, and terminal outcomes with the correct attempt lineage.
- Queued, superseded, rejected, partially constructed, and failed child resources are closed and detached.
- Realtime can achieve destination-level exactly-once completion projection only by writing through the atomic durable inbox API. Legacy and external delivery remain claim-and-retry.

Independent Phase 3 evidence: six adversarial production-adapter probes, 268 broad regressions, three TUI checks, Ruff, and diff checks passed.

## Phase 4 requirements

- Connect the Realtime session manager to the durable inbox consumer.
- Expose versioned, conversation-owned session, snapshot, event, approval, and worker-control APIs.
- Prove reconnect and restart delivery end to end.
- Keep non-atomic delivery semantics explicitly described as claim-and-retry.
- Keep Voice Console Realtime disabled until the complete contract passes its gate.
