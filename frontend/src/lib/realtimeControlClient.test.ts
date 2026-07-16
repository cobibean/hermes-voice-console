import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { RealtimeControlClient } from './realtimeControlClient';

type Listener = (event: { data?: string }) => void;
class FakeSocket {
  static OPEN = 1;
  readyState = 0;
  bufferedAmount = 0;
  sent: string[] = [];
  listeners: Record<string, Listener[]> = {};
  addEventListener(type: string, listener: Listener): void { (this.listeners[type] ??= []).push(listener); }
  send(value: string): void { this.sent.push(value); }
  close(): void { this.readyState = 3; this.emit('close'); }
  emit(type: string, value: object = {}): void {
    if (type === 'open') this.readyState = FakeSocket.OPEN;
    for (const listener of this.listeners[type] ?? []) listener(value);
  }
  json(value: object): void { this.emit('message', { data: JSON.stringify(value) }); }
}

describe('RealtimeControlClient', () => {
  beforeEach(() => vi.stubGlobal('WebSocket', FakeSocket));
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('authenticates, snapshots before replay, deduplicates events, and sends commands server-side', async () => {
    const sockets: FakeSocket[] = [];
    const snapshots = vi.fn();
    const events = vi.fn();
    const client = new RealtimeControlClient({
      getToken: vi.fn(async () => 'secret'), target: 'fake', conversationId: 'hvc_1', sessionId: 'rt_1',
      onSnapshot: snapshots, onEvent: events, createSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket as unknown as WebSocket; },
      reconnect: false,
    });
    const connected = client.connect();
    expect(client.connect()).toBe(connected);
    sockets[0].emit('open');
    await Promise.resolve();
    expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: 'auth', token: 'secret' });
    sockets[0].json({ type: 'auth.ok', principal_kind: 'development', expires_at: null });
    expect(JSON.parse(sockets[0].sent[1])).toEqual(expect.objectContaining({ type: 'subscribe', conversation_id: 'hvc_1', realtime_session_id: 'rt_1' }));
    sockets[0].json({ type: 'event', event: { event_id: 'ev_early', type: 'worker.running', conversation_id: 'hvc_1', payload: {} } });
    expect(events).not.toHaveBeenCalled();
    sockets[0].json({ type: 'snapshot', snapshot: { conversation_id: 'hvc_1', last_event_id: 'ev_1', worker_jobs: [{ worker_job_id: 'job_1', status: 'running' }] } });
    sockets[0].json({ type: 'subscribed', realtime_session_id: 'rt_1', after: 'ev_1', cursor_rebased: true });
    await connected;
    sockets[0].json({ type: 'event', event: { event_id: 'ev_2', type: 'worker.running', conversation_id: 'hvc_1', payload: { worker_job_id: 'job_1' } } });
    sockets[0].json({ type: 'event', event: { event_id: 'ev_2', type: 'worker.running', conversation_id: 'hvc_1', payload: { worker_job_id: 'job_1' } } });
    expect(events).toHaveBeenCalledTimes(1);
    expect(snapshots).toHaveBeenCalledWith(expect.objectContaining({ conversation_id: 'hvc_1' }), 'initial');
    client.input('input-1', 'hello', 2);
    expect(JSON.parse(sockets[0].sent.at(-1)!)).toEqual({ type: 'input', client_request_id: 'input-1', text: 'hello', session_generation: 2 });
    client.close();
  });

  it('reconnects from its snapshot cursor and closes without another retry', async () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const client = new RealtimeControlClient({
      getToken: vi.fn(async () => null), target: 'fake', conversationId: 'hvc_1', sessionId: 'rt_1', after: 'ev_7',
      onSnapshot: vi.fn(), onEvent: vi.fn(), reconnectDelayMs: 10,
      createSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket as unknown as WebSocket; },
    });
    const first = client.connect();
    sockets[0].emit('open'); await Promise.resolve();
    sockets[0].json({ type: 'auth.ok', principal_kind: 'development', expires_at: null });
    sockets[0].json({ type: 'snapshot', snapshot: { conversation_id: 'hvc_1', last_event_id: 'ev_7' } });
    sockets[0].json({ type: 'subscribed', realtime_session_id: 'rt_1', after: 'ev_7', cursor_rebased: false });
    await first;
    sockets[0].emit('close');
    await vi.advanceTimersByTimeAsync(10);
    expect(sockets).toHaveLength(2);
    sockets[1].emit('open'); await Promise.resolve();
    sockets[1].json({ type: 'auth.ok', principal_kind: 'development', expires_at: null });
    expect(JSON.parse(sockets[1].sent[1])).toEqual(expect.objectContaining({ after: 'ev_7' }));
    client.close();
    await vi.advanceTimersByTimeAsync(100);
    expect(sockets).toHaveLength(2);
  });

  it('fails closed under websocket backpressure', async () => {
    const socket = new FakeSocket();
    const client = new RealtimeControlClient({
      getToken: vi.fn(async () => null), target: 'fake', conversationId: 'hvc_1', sessionId: 'rt_1',
      onSnapshot: vi.fn(), onEvent: vi.fn(), createSocket: () => socket as unknown as WebSocket, reconnect: false, maxBufferedBytes: 10,
    });
    const connected = client.connect(); socket.emit('open'); await Promise.resolve();
    socket.json({ type: 'auth.ok', principal_kind: 'development', expires_at: null });
    socket.json({ type: 'snapshot', snapshot: { conversation_id: 'hvc_1', last_event_id: null } });
    socket.json({ type: 'subscribed', realtime_session_id: 'rt_1', after: null, cursor_rebased: false });
    await connected;
    socket.bufferedAmount = 11;
    expect(() => client.interrupt('interrupt-1', 1)).toThrow('backpressured');
  });
});
