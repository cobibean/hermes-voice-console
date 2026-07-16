# Realtime Rollout and Release Lane

This is the operational source of truth for Phases 9 and 10 of the GPT-Realtime-2.1 plan. It deliberately stops before external deployment and owner acceptance.

## Current local readiness

As of 2026-07-15, this checkout contains no live `config/voice.yaml` or `config/targets.yaml`. Only fake and example targets are available, so there is no identified staging host, deployment service, target credential, or rollback build to mutate from this repository.

The generic Hermes capability is locally pinned to `d41e793a355ae1bb9dc2c974d1fd2edc8b6c6a61`. The compatibility manifest remains globally disabled, and production must stay disabled until the owner completes the real desktop and physical-phone acceptance gate.

## Target-scoped staging preflight

Start from `config/targets.realtime-staging.example.yaml`. Use a dedicated staging profile and API key. Exactly one target may have `realtime_enabled: true`; production targets remain false.

Run the supported-pin lane from the clean Hermes capability checkout. Fetch upstream immediately before creating a second clean disposable checkout, then pass the fetched SHA explicitly. The current-main result is advisory, but the lane itself is required evidence:

```bash
export HERMES_REALTIME_TARGET=staging-hermes
export HERMES_REALTIME_TARGETS=/absolute/path/to/targets.staging.yaml
export HERMES_REALTIME_REPO=/absolute/path/to/hermes-supported-pin
export HERMES_CURRENT_MAIN_REPO=/absolute/path/to/hermes-current-main
export HERMES_CURRENT_MAIN_SHA="$(git -C "$HERMES_CURRENT_MAIN_REPO" rev-parse origin/main)"
make realtime-staging-gate
```

The gate proves all of the following before deployment:

- the tracked compatibility default is still `enabled: false`;
- GPT-Realtime-2.1 and GPT-5.6 remain the configured platform and lead-worker models;
- only the selected staging target is enabled;
- its target API-key environment variable is present without printing its value;
- the supported Hermes checkout is exactly the tested pin and passes the contract suite;
- current upstream is reported separately as compatible or preflight-blocked, never silently treated as the release build;
- owner and physical-phone acceptance remain explicitly pending.

The current-main lane is an upgrade warning lane. A failure there does not invalidate the tested production pin, but it blocks upgrading Hermes until the disposable checkout passes the same suite.

## External deployment gate

Before any external write, the owner must provide or approve:

1. A non-production Hermes host/profile and its service-management path.
2. The live Voice Console deployment target and HTTPS access path.
3. A unique target API key supplied only through the deployment secret store.
4. The exact pre-deployment Hermes commit/build to restore during rollback.
5. Permission to restart the staging Hermes and Voice Console services.

Then execute in order:

1. Record the existing profile, SOUL, workspace, SessionDB, memory, tools, approval rules, Telegram/CLI/cron models, and Hermes build without recording secrets or transcript content.
2. Install the supported pin only on the staging agent/profile.
3. Keep Voice Console's global default disabled and enable Realtime only for the selected target.
4. Run capability preflight and the live GPT-Realtime-2.1/GPT-5.6 smoke.
5. Prove Legacy turn-based voice before starting Realtime acceptance.
6. Complete desktop Chrome and physical-phone acceptance from the locked plan, including backgrounding, rotation, coarse-pointer landscape, manual mode, network change, approvals, reconnect, and durable worker continuity.
7. Verify Telegram, CLI, cron, and other platforms retained their configured models and behavior.

Do not translate browser viewport emulation or screenshots into physical-phone acceptance. Do not set the tracked compatibility manifest to enabled. Do not make Realtime the production default before the owner passes all fourteen acceptance steps.

## Rollback

Rollback preserves conversations and worker evidence. It does not delete Voice Console state or Hermes SessionDB data.

1. Set `realtime_enabled: false` for the affected target and restart only the Voice Console service.
2. Verify the local configuration is disabled:

   ```bash
   export HERMES_REALTIME_TARGET=staging-hermes
   export HERMES_REALTIME_TARGETS=/absolute/path/to/targets.staging.yaml
   make realtime-rollback-gate
   ```

3. Confirm Legacy turn-based voice and non-voice Hermes platforms remain healthy.
4. If the Hermes capability build caused the incident, restore the exact pre-deployment build recorded before staging and restart that staging service.
5. Preserve content-safe session/job/approval evidence for diagnosis. Never retry an `outcome_unknown` worker automatically.

The rollback gate checks configuration only; it does not restart services or change a remote agent.

## Release and upgrade policy

- Supported-pin failure blocks release.
- Current-main failure warns and blocks upgrade, not the already tested pin.
- Model availability is checked independently from contract support.
- A model selector entry is never compatibility proof.
- Production remains pinned until equivalent upstream support passes the suite.
- No issue, pull request, push, or deployment is automatic. Use the prepared upstream handoff and obtain owner approval before any external write.

## Remaining acceptance record

Create a dated phase memory note after the real run. Record the Voice Console commit, Hermes candidate and rollback commits, target label, device/browser and network class, acceptance results, non-voice regression result, and rollback proof. Do not record keys, raw audio, transcripts, responses, or sensitive tool arguments.
