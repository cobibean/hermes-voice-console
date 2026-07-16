import type { AuthTokenProvider } from './api';
import type {
  RealtimeControlFrame,
  RealtimeControlState,
  RealtimeEvent,
  RealtimeApprovalResult,
  RealtimeInputResult,
  RealtimeInterruptResult,
  RealtimeManualAudioCommitResult,
  RealtimeManualAudioDiscardResult,
  RealtimeSnapshot,
  RealtimeTurnModeResult,
  RealtimeWorkerCommandResult,
} from './realtimeTypes';

export interface RealtimeControlOptions {
  getToken: AuthTokenProvider;
  target: string;
  conversationId: string;
  sessionId: string;
  after?: string | null;
  onSnapshot: (snapshot: RealtimeSnapshot, reason: 'initial' | 'gap') => void;
  onEvent: (event: RealtimeEvent) => void;
  onState?: (state: RealtimeControlState) => void;
  onError?: (message: string) => void;
  createSocket?: (url: string) => WebSocket;
  reconnect?: boolean;
  reconnectDelayMs?: number;
  maxBufferedBytes?: number;
}

type Command = Record<string, unknown> & { type: string; client_request_id: string };
type ResultKind = 'input' | 'interrupt' | 'approval' | 'manual_audio_commit' | 'manual_audio_discard' | 'turn_mode_update' | 'worker';
interface PendingCommand {
  kind: ResultKind;
  command: Command;
  resolve: (result: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  timeout: number;
}

/** Authoritative non-media channel. It snapshots before replay and deduplicates by event ID. */
export class RealtimeControlClient {
  private readonly options: RealtimeControlOptions;
  private socket: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;
  private reconnectTimer: number | null = null;
  private closedByOwner = false;
  private snapshotReceived = false;
  private cursor: string | null;
  private readonly seen = new Set<string>();
  private socketGeneration = 0;
  private readonly pending = new Map<string, PendingCommand>();

  constructor(options: RealtimeControlOptions) {
    this.options = options;
    this.cursor = options.after ?? null;
  }

  get isReady(): boolean { return this.socket?.readyState === WebSocket.OPEN && this.snapshotReceived; }
  get replayCursor(): string | null { return this.cursor; }

  connect(): Promise<void> {
    if (this.isReady) return Promise.resolve();
    if (this.connectPromise) return this.connectPromise;
    this.closedByOwner = false;
    const promise = this.open().finally(() => {
      if (this.connectPromise === promise) this.connectPromise = null;
    });
    this.connectPromise = promise;
    return promise;
  }

  private async open(): Promise<void> {
    this.options.onState?.(this.socket ? 'reconnecting' : 'authenticating');
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${scheme}//${window.location.host}/ws/realtime`;
    const socket = this.options.createSocket?.(url) ?? new WebSocket(url);
    const generation = ++this.socketGeneration;
    this.socket = socket;
    this.snapshotReceived = false;
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const current = () => this.socket === socket && this.socketGeneration === generation;
      const fail = (error: Error) => {
        if (!settled) { settled = true; reject(error); }
      };
      socket.addEventListener('open', () => {
        if (!current()) return;
        void this.options.getToken(false)
          .then((token) => {
            if (current() && socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'auth', token }));
            }
          })
          .catch((error: unknown) => {
            if (!current()) return;
            fail(error as Error);
            socket.close();
          });
      }, { once: true });
      socket.addEventListener('error', () => {
        if (!current()) return;
        fail(new Error('Realtime control connection failed'));
        socket.close();
      }, { once: true });
      socket.addEventListener('message', (message) => {
        if (!current()) return;
        if (typeof message.data !== 'string') return;
        let frame: RealtimeControlFrame;
        try { frame = JSON.parse(message.data) as RealtimeControlFrame; }
        catch { this.options.onError?.('Received malformed Realtime control data'); return; }
        if (frame.type === 'auth.ok') {
          this.options.onState?.('subscribing');
          socket.send(JSON.stringify({
            type: 'subscribe',
            target: this.options.target,
            conversation_id: this.options.conversationId,
            realtime_session_id: this.options.sessionId,
            after: this.cursor,
          }));
          return;
        }
        if (frame.type === 'snapshot') {
          try { this.acceptSnapshot(frame.snapshot, 'initial'); }
          catch (error) { fail(error as Error); socket.close(); }
          return;
        }
        if (frame.type === 'subscribed') {
          if (!this.snapshotReceived) {
            fail(new Error('Realtime control subscribed without an authoritative snapshot'));
            socket.close();
            return;
          }
          this.cursor = frame.after;
          this.options.onState?.('ready');
          if (!settled) { settled = true; resolve(); }
          return;
        }
        if (frame.type === 'replay.gap') {
          try { this.acceptSnapshot(frame.snapshot, 'gap'); }
          catch (error) { this.options.onError?.((error as Error).message); socket.close(); return; }
          this.cursor = frame.after;
          return;
        }
        if (frame.type === 'event') {
          if (!this.snapshotReceived || this.seen.has(frame.event.event_id)) return;
          if (
            frame.event.conversation_id !== this.options.conversationId
            || (frame.event.realtime_session_id && frame.event.realtime_session_id !== this.options.sessionId)
          ) {
            this.options.onError?.('Ignored a mismatched Realtime control event');
            return;
          }
          this.seen.add(frame.event.event_id);
          while (this.seen.size > 2_000) this.seen.delete(this.seen.values().next().value!);
          this.cursor = frame.event.event_id;
          this.options.onEvent(frame.event);
          return;
        }
        if (frame.type === 'heartbeat') {
          socket.send(JSON.stringify({ type: 'heartbeat.ack' }));
          return;
        }
        if (frame.type === 'ack') {
          this.resolveCommand(frame.client_request_id, frame.result);
          return;
        }
        if (frame.type === 'error') {
          this.options.onError?.(frame.message);
          this.options.onState?.('degraded');
          this.rejectCommands(new Error(frame.message));
          if (!settled) {
            fail(new Error(frame.message));
            socket.close();
          }
        }
      });
      socket.addEventListener('close', () => {
        if (!current()) return;
        this.socket = null;
        this.snapshotReceived = false;
        this.rejectCommands(new Error('Realtime control connection closed'));
        if (!settled) fail(new Error('Realtime control closed before ready'));
        if (!this.closedByOwner && this.options.reconnect !== false) this.scheduleReconnect();
        else this.options.onState?.('closed');
      });
    });
  }

  private acceptSnapshot(snapshot: RealtimeSnapshot, reason: 'initial' | 'gap'): void {
    if (snapshot.conversation_id !== this.options.conversationId) {
      throw new Error('Realtime snapshot conversation mismatch');
    }
    this.snapshotReceived = true;
    this.cursor = snapshot.last_event_id;
    this.options.onSnapshot(snapshot, reason);
  }

  private scheduleReconnect(): void {
    if (this.closedByOwner || this.reconnectTimer !== null) return;
    this.options.onState?.('reconnecting');
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect().catch((error: unknown) => {
        this.options.onError?.((error as Error).message);
        if (!this.closedByOwner) this.scheduleReconnect();
      });
    }, this.options.reconnectDelayMs ?? 750);
  }

  private validateResult(pending: PendingCommand, requestId: string, raw: unknown): Record<string, unknown> {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Hermes returned an invalid control acknowledgement');
    const result = raw as Record<string, unknown>;
    const { kind, command } = pending;
    const idKey = kind === 'worker' ? 'command_id' : 'client_request_id';
    if (result[idKey] !== requestId) throw new Error('Hermes returned a mismatched control acknowledgement');
    if (kind === 'input' && (result.accepted !== true || result.state !== 'accepted')) throw new Error('Hermes rejected the typed input');
    if (kind === 'interrupt' && (result.interrupted !== true || result.state !== 'accepted' || result.realtime_session_id !== this.options.sessionId)) throw new Error('Hermes rejected the speech interruption');
    if (kind === 'approval' && (typeof result.accepted !== 'boolean' || !['resolved', 'denied'].includes(String(result.state)) || result.approval_id !== command.approval_id)) throw new Error('Hermes returned an invalid approval acknowledgement');
    if (kind === 'manual_audio_commit') {
      if (['in_progress', 'outcome_unknown'].includes(String(result.state))) {
        if (result.accepted !== false || (result.operation !== undefined && result.operation !== kind)) throw new Error('Hermes returned an invalid manual audio acknowledgement');
      } else if (result.state === 'rejected') {
        const error = result.error;
        if (result.accepted !== false || result.operation !== kind || !error || typeof error !== 'object' || (error as Record<string, unknown>).code !== 'audio_buffer_empty') throw new Error('Hermes returned an invalid empty audio acknowledgement');
      } else if (
        result.state !== 'accepted'
        || result.realtime_session_id !== this.options.sessionId
        || result.session_generation !== command.session_generation
        || result.audio_commit_requested !== true
        || result.response_requested !== true
      ) throw new Error('Hermes returned an invalid manual audio acknowledgement');
    }
    if (kind === 'manual_audio_discard') {
      if (['in_progress', 'outcome_unknown'].includes(String(result.state))) {
        if (result.accepted !== false || (result.operation !== undefined && result.operation !== kind)) throw new Error('Hermes returned an invalid manual discard acknowledgement');
      } else if (result.state === 'rejected') {
        const error = result.error;
        if (result.accepted !== false || result.operation !== kind || !error || typeof error !== 'object' || (error as Record<string, unknown>).code !== 'audio_discard_rejected') throw new Error('Hermes returned an invalid manual discard rejection');
      } else if (
        result.state !== 'accepted'
        || result.realtime_session_id !== this.options.sessionId
        || result.session_generation !== command.session_generation
        || result.audio_discard_requested !== true
      ) throw new Error('Hermes returned an invalid manual discard acknowledgement');
    }
    if (kind === 'turn_mode_update') {
      if (['in_progress', 'outcome_unknown'].includes(String(result.state))) {
        if (result.accepted !== false || (result.operation !== undefined && result.operation !== kind)) throw new Error('Hermes returned an invalid turn mode acknowledgement');
      } else if (result.state === 'rejected') {
        const error = result.error;
        const keys = Object.keys(result).sort().join(',');
        if (
          keys !== 'accepted,client_request_id,error,operation,state'
          || result.operation !== kind
          || result.accepted !== false
          || !error
          || typeof error !== 'object'
          || Array.isArray(error)
          || Object.keys(error).join(',') !== 'code'
          || (error as Record<string, unknown>).code !== 'turn_mode_rejected'
        ) throw new Error('Hermes returned an invalid turn mode rejection');
      } else if (
        result.state !== 'accepted'
        || result.realtime_session_id !== this.options.sessionId
        || result.session_generation !== command.session_generation
        || result.turn_mode !== command.turn_mode
      ) throw new Error('Hermes returned an invalid turn mode acknowledgement');
    }
    if (kind === 'worker') {
      const acknowledgements = new Set([
        'applied', 'already_applied', 'rejected_wrong_owner', 'rejected_terminal',
        'rejected_stale_revision', 'rejected_no_steering', 'rejected_not_signaled',
        'rejected_not_terminal', 'rejected_unclaimed',
      ]);
      if (typeof result.revision !== 'number' || !Number.isInteger(result.revision) || result.revision < 0) throw new Error('Hermes returned an invalid worker revision');
      if (typeof result.control_signal_sent !== 'boolean' || !acknowledgements.has(String(result.acknowledgement))) throw new Error('Hermes returned an invalid worker acknowledgement');
      if (result.operation !== command.operation || result.worker_job_id !== command.worker_job_id) throw new Error('Hermes returned a mismatched worker acknowledgement');
    }
    return result;
  }

  private resolveCommand(requestId: string, raw: unknown): void {
    const pending = this.pending.get(requestId);
    if (!pending) return;
    window.clearTimeout(pending.timeout);
    this.pending.delete(requestId);
    try { pending.resolve(this.validateResult(pending, requestId, raw)); }
    catch (error) { pending.reject(error as Error); }
  }

  private rejectCommands(error: Error): void {
    for (const pending of this.pending.values()) {
      window.clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
  }

  send(command: Command, kind: ResultKind): Promise<Record<string, unknown>> {
    if (!this.isReady || !this.socket) throw new Error('Hermes Realtime control is not ready');
    if (this.socket.bufferedAmount > (this.options.maxBufferedBytes ?? 256 * 1024)) {
      this.options.onState?.('degraded');
      throw new Error('Hermes Realtime control is backpressured');
    }
    if (this.pending.size >= 128) throw new Error('Too many pending Hermes control commands');
    if (this.pending.has(command.client_request_id)) throw new Error('Duplicate Hermes control request ID');
    this.options.onState?.('ready');
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        this.pending.delete(command.client_request_id);
        reject(new Error(`Hermes ${kind} acknowledgement timed out`));
      }, 15_000);
      this.pending.set(command.client_request_id, { kind, command, resolve, reject, timeout });
      try { this.socket!.send(JSON.stringify(command)); }
      catch (error) {
        window.clearTimeout(timeout);
        this.pending.delete(command.client_request_id);
        reject(error as Error);
      }
    });
  }

  async input(clientRequestId: string, text: string, sessionGeneration: number): Promise<RealtimeInputResult> {
    return await this.send({ type: 'input', client_request_id: clientRequestId, text, session_generation: sessionGeneration }, 'input') as unknown as RealtimeInputResult;
  }
  async interrupt(clientRequestId: string, sessionGeneration: number): Promise<RealtimeInterruptResult> {
    return await this.send({ type: 'interrupt', client_request_id: clientRequestId, session_generation: sessionGeneration }, 'interrupt') as unknown as RealtimeInterruptResult;
  }
  async approval(clientRequestId: string, approvalId: string, choice: string, sessionGeneration: number): Promise<RealtimeApprovalResult> {
    return await this.send({ type: 'approval', client_request_id: clientRequestId, approval_id: approvalId, choice, session_generation: sessionGeneration }, 'approval') as unknown as RealtimeApprovalResult;
  }
  async manualAudioCommit(clientRequestId: string, sessionGeneration: number): Promise<RealtimeManualAudioCommitResult> {
    return await this.send({ type: 'manual_audio_commit', client_request_id: clientRequestId, session_generation: sessionGeneration }, 'manual_audio_commit') as unknown as RealtimeManualAudioCommitResult;
  }
  async manualAudioDiscard(clientRequestId: string, sessionGeneration: number): Promise<RealtimeManualAudioDiscardResult> {
    return await this.send({ type: 'manual_audio_discard', client_request_id: clientRequestId, session_generation: sessionGeneration }, 'manual_audio_discard') as unknown as RealtimeManualAudioDiscardResult;
  }
  async turnModeUpdate(clientRequestId: string, sessionGeneration: number, turnMode: 'automatic' | 'manual'): Promise<RealtimeTurnModeResult> {
    return await this.send({ type: 'turn_mode_update', client_request_id: clientRequestId, session_generation: sessionGeneration, turn_mode: turnMode }, 'turn_mode_update') as unknown as RealtimeTurnModeResult;
  }
  async workerCommand(
    clientRequestId: string,
    workerJobId: string,
    operation: 'refine' | 'redirect' | 'cancel',
    expectedRevision: number,
    payload: Record<string, unknown> = {},
  ): Promise<RealtimeWorkerCommandResult> {
    return await this.send({ type: 'worker.command', client_request_id: clientRequestId, worker_job_id: workerJobId, operation, expected_revision: expectedRevision, payload }, 'worker') as unknown as RealtimeWorkerCommandResult;
  }

  close(): void {
    this.closedByOwner = true;
    this.socketGeneration += 1;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.connectPromise = null;
    this.snapshotReceived = false;
    this.rejectCommands(new Error('Realtime control connection closed'));
    this.socket?.close();
    this.socket = null;
    this.options.onState?.('closed');
  }
}
