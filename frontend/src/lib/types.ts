export interface TargetInfo {
  name: string;
  label: string;
  base_url: string;
  default_session_key: string;
  preferred_transport: string;
  api_key_configured: boolean;
  voice?: { tts_voice?: string };
}

export interface Bootstrap {
  server: { public_base_url: string; auth_required: boolean };
  voice: {
    stt_provider: string;
    tts_provider: string;
    sample_rate: number;
    max_recording_seconds: number;
    speak_replies_default: boolean;
  };
  targets: TargetInfo[];
}

export type VoiceServerEvent =
  | { type: 'ready'; target: string; session_id: string; capabilities: Record<string, unknown>; stt_provider: string; tts_provider: string; speak_replies: boolean }
  | { type: 'recording.started'; turn_id: string }
  | { type: 'recording.stopped'; turn_id: string }
  | { type: 'transcript.final'; turn_id: string; text: string; provider?: string }
  | { type: 'agent.run.started'; run_id: string; session_id: string }
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
  | { type: 'tts.start'; turn_id: string; mime: string; provider?: string }
  | { type: 'tts.end'; turn_id: string }
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
