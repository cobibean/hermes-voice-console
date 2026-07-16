import type { AuthTokenProvider } from './api';
import type {
  RealtimeControlFrame,
  RealtimeControlState,
  RealtimeEvent,
  RealtimeSnapshot,
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
    this.socket = socket;
    this.snapshotReceived = false;
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const fail = (error: Error) => {
        if (!settled) { settled = true; reject(error); }
      };
      socket.addEventListener('open', () => {
        void this.options.getToken(false)
          .then((token) => {
            if (this.socket === socket && socket.readyState === WebSocket.OPEN) {
              socket.send(JSON.stringify({ type: 'auth', token }));
            }
          })
          .catch((error: unknown) => fail(error as Error));
      }, { once: true });
      socket.addEventListener('error', () => fail(new Error('Realtime control connection failed')), { once: true });
      socket.addEventListener('message', (message) => {
        if (this.socket !== socket) return;
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
          if (!this.snapshotReceived) { fail(new Error('Realtime control subscribed without an authoritative snapshot')); return; }
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
        if (frame.type === 'error') {
          this.options.onError?.(frame.message);
          if (!settled) fail(new Error(frame.message));
        }
      });
      socket.addEventListener('close', () => {
        if (this.socket === socket) this.socket = null;
        this.snapshotReceived = false;
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

  send(command: Command): void {
    if (!this.isReady || !this.socket) throw new Error('Hermes Realtime control is not ready');
    if (this.socket.bufferedAmount > (this.options.maxBufferedBytes ?? 256 * 1024)) {
      this.options.onState?.('degraded');
      throw new Error('Hermes Realtime control is backpressured');
    }
    this.options.onState?.('ready');
    this.socket.send(JSON.stringify(command));
  }

  input(clientRequestId: string, text: string, sessionGeneration: number): void {
    this.send({ type: 'input', client_request_id: clientRequestId, text, session_generation: sessionGeneration });
  }
  interrupt(clientRequestId: string, sessionGeneration: number): void {
    this.send({ type: 'interrupt', client_request_id: clientRequestId, session_generation: sessionGeneration });
  }
  approval(clientRequestId: string, approvalId: string, choice: string, sessionGeneration: number): void {
    this.send({ type: 'approval', client_request_id: clientRequestId, approval_id: approvalId, choice, session_generation: sessionGeneration });
  }
  workerCommand(
    clientRequestId: string,
    workerJobId: string,
    operation: 'refine' | 'redirect' | 'cancel',
    expectedRevision: number,
    payload: Record<string, unknown> = {},
  ): void {
    this.send({ type: 'worker.command', client_request_id: clientRequestId, worker_job_id: workerJobId, operation, expected_revision: expectedRevision, payload });
  }

  close(): void {
    this.closedByOwner = true;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.connectPromise = null;
    this.snapshotReceived = false;
    this.socket?.close();
    this.socket = null;
    this.options.onState?.('closed');
  }
}
