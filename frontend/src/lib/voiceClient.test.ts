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
  beforeEach(() => {
    sockets = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });
  afterEach(() => {
    vi.stubGlobal('WebSocket', OriginalWebSocket);
  });

  it('connect resolves only after backend ready', async () => {
    let resolved = false;
    const client = new VoiceClient({ token: 'tok', onEvent: vi.fn(), onAudio: vi.fn() });
    const promise = client.connect({ target: 'fake', sessionId: 's1', speakReplies: true }).then(() => { resolved = true; });
    sockets[0].emit('open', {});
    await Promise.resolve();
    expect(resolved).toBe(false);
    sockets[0].emitJson({ type: 'ready', target: 'fake', session_id: 's1', capabilities: {}, stt_provider: 'fake', tts_provider: 'fake', speak_replies: true });
    await promise;
    expect(resolved).toBe(true);
  });

  it('startRecording waits for matching recording.started', async () => {
    const client = new VoiceClient({ token: 'tok', onEvent: vi.fn(), onAudio: vi.fn() });
    const connect = client.connect({ target: 'fake', sessionId: 's1', speakReplies: false });
    sockets[0].emit('open', {});
    sockets[0].emitJson({ type: 'ready', target: 'fake', session_id: 's1', capabilities: {}, stt_provider: 'fake', tts_provider: 'fake', speak_replies: false });
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
});
