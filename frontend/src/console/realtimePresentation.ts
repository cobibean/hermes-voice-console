export type RealtimeReadiness =
  | 'connecting_audio'
  | 'attaching_hermes'
  | 'live'
  | 'recovering'
  | 'degraded'
  | 'disconnected'
  | 'blocked';

export const MOBILE_TOUCH_TARGET_PX = 44;

export type WorkerJobStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface WorkerJobToolActivity {
  id: string;
  label: string;
  status: 'running' | 'completed' | 'failed';
  detail?: string;
}
export interface WorkerJobArtifact {
  id: string;
  label: string;
  href?: string;
  kind?: string;
}

export interface WorkerJobPresentation {
  id: string;
  title: string;
  status: WorkerJobStatus;
  summary?: string;
  progress?: number;
  queuePosition?: number;
  attempt?: number;
  parentAttemptId?: string;
  tools?: WorkerJobToolActivity[];
  artifacts?: WorkerJobArtifact[];
  verification?: string;
  approvalMessage?: string;
}

export interface RealtimePresentationModel {
  mode: 'realtime' | 'legacy';
  /** `live` means both browser media and authoritative Hermes control are ready. */
  readiness: RealtimeReadiness;
  readinessDetail?: string;
  canReconnect: boolean;
  muted: boolean;
  manualTurnTaking: boolean;
  manualCaptureState?: 'idle' | 'starting' | 'capturing' | 'committing' | 'discarding' | 'error';
  manualCaptureError?: string;
  listening: boolean;
  speaking: boolean;
  jobs: WorkerJobPresentation[];
  onToggleMute?: () => void;
  onToggleManualTurnTaking?: () => void;
  onStartManualTurn?: () => void;
  onSendManualTurn?: () => void;
  onDiscardManualTurn?: () => void;
  onInterrupt?: () => void;
  onEndCall?: () => void;
  onReconnect?: () => void;
  onUseLegacy?: () => void;
  onRequestStatus?: (jobId: string) => void;
  onRefine?: (jobId: string) => void;
  onRedirect?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
  artifactAllowedOrigins?: string[];
}
