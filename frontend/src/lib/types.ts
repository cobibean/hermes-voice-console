export interface TargetInfo {
  name: string;
  label: string;
  preferred_transport: string;
  api_key_configured: boolean;
  configured_provider_label?: string | null;
  configured_model_label?: string | null;
  realtime_enabled?: boolean;
  voice?: { tts_voice?: string };
}

export type AuthMode = 'clerk' | 'service' | 'development';

export interface PublicConfig {
  auth_mode: AuthMode;
  clerk_publishable_key: string | null;
  public_base_url: string;
}

export interface Bootstrap {
  server: { public_base_url: string; auth_mode: AuthMode };
  principal: { kind: string; owner_key: string };
  voice: {
    stt_provider: string;
    tts_provider: string;
    sample_rate: number;
    max_recording_seconds: number;
    speak_replies_default: boolean;
  };
  targets: TargetInfo[];
}

export interface SessionInfo {
  conversation_id: string;
  target: string;
  title: string;
  created_at: number;
  updated_at: number;
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  id?: string;
  tool?: string;
  status?: 'running' | 'completed' | 'failed';
  duration?: number;
  runId?: string;
}

export type VoiceServerEvent =
  | { type: 'auth.ok'; principal_kind: string; expires_at: number | null }
  | { type: 'auth.expiring'; expires_at: number }
  | { type: 'auth.refreshed'; expires_at: number }
  | { type: 'run.acceptance_unknown'; turn_id: string; local_turn_id: string; message: string }
  | { type: 'run.acceptance_unknown.acknowledged'; local_turn_id: string }
  | { type: 'run.unrecoverable'; run_id: string; turn_id: string; error: string }
  | { type: 'run.unrecoverable.acknowledged'; run_id: string }
  | { type: 'run.snapshot'; run_id: string; status: string; last_sequence: number; gap: boolean }
  | { type: 'ready'; target: string; conversation_id: string; capabilities: Record<string, unknown>; stt_provider: string; tts_provider: string; speak_replies: boolean }
  | { type: 'recording.started'; turn_id: string }
  | { type: 'recording.stopped'; turn_id: string }
  | { type: 'recording.discarded'; turn_id: string }
  | { type: 'text.accepted'; turn_id: string }
  | { type: 'transcript.final'; turn_id: string; text: string; provider?: string }
  | { type: 'agent.run.started'; run_id: string; session_id: string; turn_id: string }
  | { type: 'agent.delta'; run_id: string; delta: string }
  | { type: 'agent.tool.started'; run_id: string; tool?: string; preview?: string }
  | { type: 'agent.tool.completed'; run_id: string; tool?: string; error?: boolean; duration?: number }
  | { type: 'agent.approval.request'; run_id: string; approval: Record<string, unknown> }
  | { type: 'agent.approval.responded'; run_id: string; choice?: string; resolved?: number }
  | { type: 'agent.approval.resolved'; run_id: string; result: Record<string, unknown> }
  | { type: 'agent.stop.requested'; run_id: string; result: Record<string, unknown> }
  | { type: 'agent.completed'; run_id: string; text: string; usage?: Record<string, unknown> }
  | { type: 'agent.failed'; run_id?: string; error: string }
  | { type: 'agent.stopped'; run_id?: string }
  | { type: 'tts.start'; turn_id: string; chunk_index: number; mime: string; provider?: string }
  | { type: 'tts.end'; turn_id: string; chunk_index: number }
  | { type: 'tts.complete'; turn_id: string }
  | { type: 'tts.cancelled'; turn_id: string }
  | { type: 'error'; code: string; message: string; recoverable: boolean }
  | { type: 'pong' }
  | { type: 'agent.event'; run_id?: string; event: Record<string, unknown> };

export interface TimelineItem {
  id: string;
  ts: number;
  kind: string;
  message: string;
  payload?: unknown;
}
