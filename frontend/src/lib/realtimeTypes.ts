export type RealtimeTurnMode = 'server_vad' | 'manual';
export type VoiceTransport = 'realtime' | 'legacy';

export interface RealtimeCompatibility {
  compatible: boolean;
  version: string | null;
  reasons: string[];
  contract: Record<string, unknown>;
}

export interface RealtimeSessionDocument {
  contract_version: string;
  realtime_session_id: string;
  conversation_id: string;
  session_generation: number;
  state: 'provisioning' | 'controller_ready' | 'client_authorized' | 'active' | 'degraded' | 'closed' | 'failed';
  answer_sdp: string;
  client_request_id: string;
}

export interface RealtimeEvent {
  event_id: string;
  type: string;
  conversation_id: string;
  realtime_session_id?: string;
  generation?: number;
  created_at?: number;
  payload: Record<string, unknown>;
}

export interface RealtimeSnapshot {
  conversation_id: string;
  last_event_id: string | null;
  session?: Record<string, unknown> | null;
  worker_jobs?: Record<string, unknown>[];
  tool_calls?: Record<string, unknown>[];
  approvals?: Record<string, unknown>[];
  pending_approvals?: Record<string, unknown>[];
  artifacts?: Record<string, unknown>[];
  transcript?: Record<string, unknown>[];
  work_summary?: Record<string, unknown>[];
  [key: string]: unknown;
}

export type RealtimeControlFrame =
  | { type: 'auth.ok'; principal_kind: string; expires_at: number | null }
  | { type: 'snapshot'; snapshot: RealtimeSnapshot }
  | { type: 'subscribed'; realtime_session_id: string; after: string | null; client_after?: string | null; cursor_rebased: boolean }
  | { type: 'event'; event: RealtimeEvent }
  | { type: 'replay.gap'; snapshot: RealtimeSnapshot; after: string | null }
  | { type: 'heartbeat'; after: string | null }
  | { type: 'pong'; after: string | null }
  | { type: 'ack'; client_request_id: string; result: Record<string, unknown> }
  | { type: 'error'; code: string; message: string; recoverable?: boolean };

export interface RealtimeInputResult { client_request_id: string; accepted: true; state: 'accepted' }
export interface RealtimeInterruptResult extends RealtimeInputResult { realtime_session_id: string; interrupted: true }
export interface RealtimeApprovalResult { client_request_id: string; approval_id: string; accepted: boolean; state: 'resolved' | 'denied' }
export interface RealtimeManualAudioCommitResult {
  client_request_id: string;
  operation?: 'manual_audio_commit';
  state: 'accepted' | 'rejected' | 'in_progress' | 'outcome_unknown';
  accepted?: boolean;
  realtime_session_id?: string;
  session_generation?: number;
  audio_commit_requested?: true;
  response_requested?: true;
  error?: { code: 'audio_buffer_empty' };
}
export interface RealtimeManualAudioDiscardResult {
  client_request_id: string;
  operation?: 'manual_audio_discard';
  state: 'accepted' | 'rejected' | 'in_progress' | 'outcome_unknown';
  accepted?: boolean;
  realtime_session_id?: string;
  session_generation?: number;
  audio_discard_requested?: true;
  error?: { code: 'audio_discard_rejected' };
}
export type RealtimeTurnModeResult =
  | {
    client_request_id: string;
    state: 'accepted';
    realtime_session_id: string;
    session_generation: number;
    turn_mode: 'automatic' | 'manual';
  }
  | {
    client_request_id: string;
    operation?: 'turn_mode_update';
    state: 'in_progress' | 'outcome_unknown';
    accepted: false;
  }
  | {
    client_request_id: string;
    operation: 'turn_mode_update';
    state: 'rejected';
    accepted: false;
    error: { code: 'turn_mode_rejected' };
  };
export interface RealtimeWorkerCommandResult {
  command_id: string;
  worker_job_id: string;
  operation: 'refine' | 'redirect' | 'cancel';
  acknowledgement:
    | 'applied'
    | 'already_applied'
    | 'rejected_wrong_owner'
    | 'rejected_terminal'
    | 'rejected_stale_revision'
    | 'rejected_no_steering'
    | 'rejected_not_signaled'
    | 'rejected_not_terminal'
    | 'rejected_unclaimed';
  revision: number;
  control_signal_sent: boolean;
}

export type RealtimeMediaState = 'idle' | 'requesting_microphone' | 'negotiating' | 'connected' | 'failed' | 'closed';
export type RealtimeControlState = 'idle' | 'authenticating' | 'subscribing' | 'ready' | 'reconnecting' | 'degraded' | 'closed';

export function realtimeRequestId(prefix = 'hvc'): string {
  const value = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${value}`;
}
