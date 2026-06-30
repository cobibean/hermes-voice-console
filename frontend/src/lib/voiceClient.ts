import type { VoiceServerEvent } from './types';

export interface VoiceClientOptions {
  token: string;
  onEvent: (event: VoiceServerEvent) => void;
  onAudio: (chunk: ArrayBuffer) => void;
  onClose?: () => void;
  onError?: (message: string) => void;
}

export interface HelloOptions {
  target: string;
  sessionId: string;
  speakReplies: boolean;
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
    const params = new URLSearchParams({ token: this.options.token, target: hello.target, session_id: hello.sessionId });
    const url = `${scheme}//${window.location.host}/ws/voice?${params.toString()}`;
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
      ws.addEventListener('open', () => {
        ws.send(JSON.stringify({
          type: 'hello',
          version: 1,
          target: hello.target,
          session_id: hello.sessionId,
          mode: 'push_to_talk',
          input_format: 'pcm16',
          input_sample_rate: 16000,
          speak_replies: hello.speakReplies,
        }));
      }, { once: true });
      ws.addEventListener('error', () => settleReject(new Error('voice websocket connection failed')), { once: true });
      ws.addEventListener('message', (ev) => {
        if (typeof ev.data === 'string') {
          try {
            const event = JSON.parse(ev.data) as VoiceServerEvent;
            this.options.onEvent(event);
            this.resolveWaiters(event);
            if (event.type === 'ready') settleResolve();
            if (event.type === 'error' && !settled) settleReject(new Error(event.message));
          } catch {
            this.options.onError?.('Received malformed voice event');
          }
        } else {
          this.options.onAudio(ev.data as ArrayBuffer);
        }
      });
      ws.addEventListener('close', () => {
        if (this.ws === ws) this.ws = null;
        this.rejectWaiters(new Error('voice websocket closed'));
        settleReject(new Error('voice websocket closed before ready'));
        this.options.onClose?.();
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

  resolveApproval(runId: string, decision: 'once' | 'session' | 'always' | 'deny'): void {
    this.sendJson({ type: 'approval.resolve', run_id: runId, decision });
  }

  stopRun(runId: string): void {
    this.sendJson({ type: 'agent.stop', run_id: runId });
  }

  cancelTts(turnId: string): void {
    this.sendJson({ type: 'tts.cancel', turn_id: turnId });
  }

  close(): void {
    this.rejectWaiters(new Error('voice websocket closed'));
    this.ws?.close();
    this.ws = null;
  }
}
