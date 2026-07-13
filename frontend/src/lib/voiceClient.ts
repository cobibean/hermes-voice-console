import type { AuthTokenProvider } from './api';
import type { AuthMode, VoiceServerEvent } from './types';
import { voiceDiagnostic } from './diagnostics';

export interface VoiceClientOptions {
  authMode: AuthMode;
  getToken: AuthTokenProvider;
  onEvent: (event: VoiceServerEvent) => void;
  onAudio: (chunk: ArrayBuffer) => void;
  onClose?: () => void;
  onError?: (message: string) => void;
}

export interface HelloOptions {
  target: string;
  conversationId: string;
  speakReplies: boolean;
  resumeRunId?: string;
  lastSequence?: number;
}

type EventPredicate = (event: VoiceServerEvent) => boolean;
interface Waiter {
  type: VoiceServerEvent['type'];
  predicate?: EventPredicate;
  resolve: (event: VoiceServerEvent) => void;
  reject: (error: Error) => void;
  timeout: number;
}

export class VoiceClient {
  private ws: WebSocket | null = null;
  private options: VoiceClientOptions;
  private waiters: Waiter[] = [];

  constructor(options: VoiceClientOptions) {
    this.options = options;
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  async connect(hello: HelloOptions): Promise<void> {
    if (this.isOpen) return;
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${scheme}//${window.location.host}/ws/voice`;
    voiceDiagnostic('socket.connect.requested', {
      target: hello.target,
      conversationId: hello.conversationId,
      recovery: Boolean(hello.resumeRunId),
      speakReplies: hello.speakReplies,
    });
    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      this.ws = ws;
      let settled = false;
      const settleReject = (err: Error) => {
        if (!settled) {
          settled = true;
          reject(err);
        }
      };
      const settleResolve = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      const sendHello = () => {
        ws.send(JSON.stringify({
          type: 'hello',
          version: 1,
          target: hello.target,
          conversation_id: hello.conversationId,
          mode: 'push_to_talk',
          input_format: 'pcm16',
          input_sample_rate: 16000,
          speak_replies: hello.speakReplies,
          resume_run_id: hello.resumeRunId,
          last_sequence: hello.lastSequence,
        }));
      };
      ws.addEventListener('open', () => {
        voiceDiagnostic('socket.open');
        void this.options.getToken(false)
          .then((token) => ws.send(JSON.stringify({ type: 'auth', token })))
          .catch((error: unknown) => settleReject(error as Error));
      }, { once: true });
      ws.addEventListener('error', () => settleReject(new Error('voice websocket connection failed')), { once: true });
      ws.addEventListener('message', (ev) => {
        if (typeof ev.data === 'string') {
          try {
            const event = JSON.parse(ev.data) as VoiceServerEvent;
            voiceDiagnostic('socket.event', {
              type: event.type,
              turnId: 'turn_id' in event ? event.turn_id : undefined,
              runId: 'run_id' in event ? event.run_id : undefined,
            }, event.type === 'agent.delta');
            if (event.type === 'auth.ok') {
              sendHello();
              return;
            }
            if (event.type === 'auth.expiring' && this.options.authMode === 'clerk') {
              void this.options.getToken(true)
                .then((token) => ws.send(JSON.stringify({ type: 'auth.refresh', token })))
                .catch((error: unknown) => this.options.onError?.((error as Error).message));
            }
            this.options.onEvent(event);
            this.resolveWaiters(event);
            if (event.type === 'ready') settleResolve();
            if (event.type === 'error' && !settled) settleReject(new Error(event.message));
          } catch {
            this.options.onError?.('Received malformed voice event');
          }
        } else {
          voiceDiagnostic('socket.audio', { bytes: (ev.data as ArrayBuffer).byteLength }, true);
          this.options.onAudio(ev.data as ArrayBuffer);
        }
      });
      ws.addEventListener('close', () => {
        if (this.ws === ws) this.ws = null;
        this.rejectWaiters(new Error('voice websocket closed'));
        settleReject(new Error('voice websocket closed before ready'));
        this.options.onClose?.();
        voiceDiagnostic('socket.closed');
      });
    });
  }

  waitFor<T extends VoiceServerEvent>(type: T['type'], predicate?: (event: T) => boolean, timeoutMs = 10_000): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const waiter: Waiter = {
        type,
        predicate: predicate ? (event) => predicate(event as T) : undefined,
        resolve: (event) => resolve(event as T),
        reject,
        timeout: window.setTimeout(() => {
          this.waiters = this.waiters.filter((item) => item !== waiter);
          reject(new Error(`Timed out waiting for ${type}`));
        }, timeoutMs),
      };
      this.waiters.push(waiter);
    });
  }

  private resolveWaiters(event: VoiceServerEvent): void {
    const pending = [...this.waiters];
    for (const waiter of pending) {
      if (waiter.type !== event.type) continue;
      if (waiter.predicate && !waiter.predicate(event)) continue;
      window.clearTimeout(waiter.timeout);
      this.waiters = this.waiters.filter((item) => item !== waiter);
      waiter.resolve(event);
    }
  }

  private rejectWaiters(error: Error): void {
    for (const waiter of this.waiters) {
      window.clearTimeout(waiter.timeout);
      waiter.reject(error);
    }
    this.waiters = [];
  }

  sendJson(payload: Record<string, unknown>): void {
    if (!this.isOpen) throw new Error('voice websocket is not connected');
    this.ws!.send(JSON.stringify(payload));
    voiceDiagnostic('socket.command', {
      type: payload.type,
      turnId: payload.turn_id,
      runId: payload.run_id,
    });
  }

  sendAudio(payload: ArrayBuffer): void {
    if (this.isOpen) this.ws!.send(payload);
  }

  async startRecording(turnId: string): Promise<void> {
    const started = this.waitFor<Extract<VoiceServerEvent, { type: 'recording.started' }>>(
      'recording.started',
      (event) => event.turn_id === turnId,
    );
    this.sendJson({ type: 'recording.start', turn_id: turnId });
    await started;
  }

  stopRecording(turnId: string): void {
    this.sendJson({ type: 'recording.stop', turn_id: turnId });
  }

  cancelRecording(turnId: string): void {
    this.sendJson({ type: 'recording.cancel', turn_id: turnId });
  }

  sendText(turnId: string, text: string): void {
    this.sendJson({ type: 'text.submit', turn_id: turnId, text });
  }

  resolveApproval(runId: string, decision: 'once' | 'session' | 'always' | 'deny'): void {
    this.sendJson({ type: 'approval.resolve', run_id: runId, decision });
  }

  stopRun(runId: string): void {
    this.sendJson({ type: 'agent.stop', run_id: runId });
  }

  cancelTts(turnId: string): void {
    this.sendJson({ type: 'tts.cancel', turn_id: turnId });
  }

  acknowledgeAcceptanceUnknown(localTurnId: string): void {
    this.sendJson({
      type: 'run.acceptance_unknown.acknowledge',
      local_turn_id: localTurnId,
    });
  }

  acknowledgeUnrecoverable(runId: string): void {
    this.sendJson({ type: 'run.unrecoverable.acknowledge', run_id: runId });
  }

  close(): void {
    this.rejectWaiters(new Error('voice websocket closed'));
    this.ws?.close();
    this.ws = null;
  }
}
