export type RealtimeConnectionState =
  | 'connecting'
  | 'live'
  | 'recovering'
  | 'disconnected'
  | 'blocked';

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
  connection: RealtimeConnectionState;
  connectionDetail?: string;
  muted: boolean;
  manualTurnTaking: boolean;
  listening: boolean;
  speaking: boolean;
  jobs: WorkerJobPresentation[];
  onToggleMute?: () => void;
  onToggleManualTurnTaking?: () => void;
  onInterrupt?: () => void;
  onReconnect?: () => void;
  onRequestStatus?: (jobId: string) => void;
  onRefine?: (jobId: string) => void;
  onRedirect?: (jobId: string) => void;
  onCancel?: (jobId: string) => void;
}
