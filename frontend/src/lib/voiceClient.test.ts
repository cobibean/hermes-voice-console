import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { VoiceClient } from './voiceClient';
import type { VoiceServerEvent } from './types';

interface ListenerMap { [key: string]: Array<(event: any) => void>; }

class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  readyState = FakeWebSocket.CONNECTING;
  binaryType = 'blob';
  sent: string[] = [];
  listeners: ListenerMap = {};
  constructor(public url: string) {
    sockets.push(this);
  }
  addEventListener(type: string, cb: (event: any) => void): void {
    this.listeners[type] = this.listeners[type] ?? [];
    this.listeners[type].push(cb);
  }
  send(payload: string): void { this.sent.push(payload); }
  close(): void { this.emit('close', {}); }
  emit(type: string, event: any): void {
    if (type === 'open') this.readyState = FakeWebSocket.OPEN;
    for (const cb of this.listeners[type] ?? []) cb(event);
  }
  emitJson(event: VoiceServerEvent): void { this.emit('message', { data: JSON.stringify(event) }); }
}

let sockets: FakeWebSocket[] = [];
const OriginalWebSocket = globalThis.WebSocket;

describe('VoiceClient', () => {
  const clientOptions = {
    authMode: 'service' as const,
    getToken: vi.fn(async () => 'tok'),
    onEvent: vi.fn(),
    onAudio: vi.fn(),
  };

  beforeEach(() => {
    sockets = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });
  afterEach(() => {
    vi.stubGlobal('WebSocket', OriginalWebSocket);
  });

  it('connect resolves only after backend ready', async () => {
    let resolved = false;
    const client = new VoiceClient(clientOptions);
    const promise = client.connect({ target: 'fake', conversationId: 's1', speakReplies: true }).then(() => { resolved = true; });
    sockets[0].emit('open', {});
    await Promise.resolve();
    expect(resolved).toBe(false);
    expect(sockets[0].url).not.toContain('token');
    expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: 'auth', token: 'tok' });
    sockets[0].emitJson({ type: 'auth.ok', principal_kind: 'service', expires_at: null });
    sockets[0].emitJson({ type: 'ready', target: 'fake', conversation_id: 's1', capabilities: {}, stt_provider: 'fake', tts_provider: 'fake', speak_replies: true });
    await promise;
    expect(resolved).toBe(true);
  });

  it('startRecording waits for matching recording.started', async () => {
    const client = new VoiceClient(clientOptions);
    const connect = client.connect({ target: 'fake', conversationId: 's1', speakReplies: false });
    sockets[0].emit('open', {});
    await Promise.resolve();
    sockets[0].emitJson({ type: 'auth.ok', principal_kind: 'service', expires_at: null });
    sockets[0].emitJson({ type: 'ready', target: 'fake', conversation_id: 's1', capabilities: {}, stt_provider: 'fake', tts_provider: 'fake', speak_replies: false });
    await connect;
    let resolved = false;
    const started = client.startRecording('turn-1').then(() => { resolved = true; });
    sockets[0].emitJson({ type: 'recording.started', turn_id: 'other' });
    await Promise.resolve();
    expect(resolved).toBe(false);
    sockets[0].emitJson({ type: 'recording.started', turn_id: 'turn-1' });
    await started;
    expect(resolved).toBe(true);
  });

  it('refreshes Clerk authentication in-band without reconnecting or using the URL', async () => {
    const getToken = vi.fn(async (skipCache = false) => (skipCache ? 'fresh' : 'cached'));
    const client = new VoiceClient({
      authMode: 'clerk',
      getToken,
      onEvent: vi.fn(),
      onAudio: vi.fn(),
    });
    const connected = client.connect({ target: 'fake', conversationId: 's1', speakReplies: false });
    sockets[0].emit('open', {});
    await Promise.resolve();
    sockets[0].emitJson({ type: 'auth.ok', principal_kind: 'clerk', expires_at: 100 });
    sockets[0].emitJson({ type: 'ready', target: 'fake', conversation_id: 's1', capabilities: {}, stt_provider: 'fake', tts_provider: 'fake', speak_replies: false });
    await connected;

    sockets[0].emitJson({ type: 'auth.expiring', expires_at: 100 });
    await Promise.resolve();
    expect(getToken).toHaveBeenLastCalledWith(true);
    expect(JSON.parse(sockets[0].sent.at(-1) ?? '{}')).toEqual({
      type: 'auth.refresh',
      token: 'fresh',
    });
    expect(sockets[0].url).toBe('ws://localhost:3000/ws/voice');
  });
});
