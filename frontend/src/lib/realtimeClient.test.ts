import { afterEach, describe, expect, it, vi } from 'vitest';
import { RealtimeClient } from './realtimeClient';
import type { RealtimeSessionDocument } from './realtimeTypes';

function fakeSession(): RealtimeSessionDocument {
  return {
    contract_version: '1.0', realtime_session_id: 'rt_1', conversation_id: 'hvc_1',
    session_generation: 1, state: 'client_authorized', answer_sdp: 'v=0\r\nanswer',
    client_request_id: 'create-1',
  };
}

class FakePeer extends EventTarget {
  connectionState = 'new';
  iceGatheringState = 'complete';
  localDescription: RTCSessionDescription | null = null;
  tracks: MediaStreamTrack[] = [];
  listenerCounts: Record<string, number> = {};
  override addEventListener(type: string, callback: EventListenerOrEventListenerObject | null, options?: boolean | AddEventListenerOptions): void {
    this.listenerCounts[type] = (this.listenerCounts[type] ?? 0) + 1;
    super.addEventListener(type, callback, options);
  }
  override removeEventListener(type: string, callback: EventListenerOrEventListenerObject | null, options?: boolean | EventListenerOptions): void {
    this.listenerCounts[type] = Math.max(0, (this.listenerCounts[type] ?? 0) - 1);
    super.removeEventListener(type, callback, options);
  }
  close = vi.fn(() => { this.connectionState = 'closed'; });
  addTrack(track: MediaStreamTrack): RTCRtpSender { this.tracks.push(track); return {} as RTCRtpSender; }
  createOffer = vi.fn(async () => ({ type: 'offer' as RTCSdpType, sdp: 'v=0\r\noffer' }));
  setLocalDescription = vi.fn(async (value: RTCSessionDescriptionInit) => { this.localDescription = value as RTCSessionDescription; });
  setRemoteDescription = vi.fn(async () => {
    this.connectionState = 'connected';
    this.dispatchEvent(new Event('connectionstatechange'));
  });
  createDataChannel = vi.fn(() => new EventTarget() as RTCDataChannel);
}

describe('RealtimeClient', () => {
  afterEach(() => vi.restoreAllMocks());

  it('creates one audio-only peer and sends only SDP through the backend exchange', async () => {
    const track = { enabled: true, stop: vi.fn(), kind: 'audio' } as unknown as MediaStreamTrack;
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
    const peer = new FakePeer();
    const exchangeSdp = vi.fn(async () => fakeSession());
    const activate = vi.fn(async () => undefined);
    const audio = { autoplay: false, srcObject: null, play: vi.fn(async () => undefined), pause: vi.fn() } as unknown as HTMLAudioElement;
    const client = new RealtimeClient({
      exchangeSdp, activate,
      createPeer: () => peer as unknown as RTCPeerConnection,
      getUserMedia: vi.fn(async () => stream),
      createAudioElement: () => audio,
    });

    const first = client.connect();
    const second = client.connect();
    expect(first).toBe(second);
    await first;
    expect(exchangeSdp).toHaveBeenCalledWith('v=0\r\noffer');
    expect(activate).toHaveBeenCalledWith(expect.objectContaining({ realtime_session_id: 'rt_1' }));
    expect(peer.createDataChannel).not.toHaveBeenCalled();
    expect(peer.tracks).toEqual([track]);

    client.setMuted(true);
    expect(track.enabled).toBe(false);
    client.close();
    client.close();
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(peer.close).toHaveBeenCalledTimes(1);
  });

  it('stops a superseded microphone stream instead of activating it', async () => {
    let release!: (stream: MediaStream) => void;
    const track = { enabled: true, stop: vi.fn() } as unknown as MediaStreamTrack;
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
    const client = new RealtimeClient({
      exchangeSdp: vi.fn(), activate: vi.fn(), createPeer: () => new FakePeer() as unknown as RTCPeerConnection,
      getUserMedia: () => new Promise((resolve) => { release = resolve; }),
    });
    const connecting = client.connect();
    client.close();
    release(stream);
    await expect(connecting).rejects.toThrow('superseded');
    expect(track.stop).toHaveBeenCalledOnce();
  });

  it('releases an upstream call exactly once when post-SDP activation fails', async () => {
    const track = { enabled: true, stop: vi.fn() } as unknown as MediaStreamTrack;
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
    const releaseSession = vi.fn(async () => undefined);
    const client = new RealtimeClient({
      exchangeSdp: vi.fn(async () => fakeSession()),
      activate: vi.fn(async () => { throw new Error('activation failed'); }),
      releaseSession,
      createPeer: () => new FakePeer() as unknown as RTCPeerConnection,
      getUserMedia: vi.fn(async () => stream),
      createAudioElement: () => ({ autoplay: false, srcObject: null, play: vi.fn(), pause: vi.fn() }) as unknown as HTMLAudioElement,
    });
    await expect(client.connect()).rejects.toThrow('activation failed');
    expect(releaseSession).toHaveBeenCalledOnce();
    client.close();
    expect(releaseSession).toHaveBeenCalledOnce();
  });

  it('rejects an outcome-unknown create response before applying invalid SDP', async () => {
    const track = { enabled: true, stop: vi.fn() } as unknown as MediaStreamTrack;
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
    const peer = new FakePeer();
    const outcomeUnknown = {
      client_request_id: 'create-unknown-1',
      operation: 'create',
      state: 'outcome_unknown',
      accepted: false,
    } as unknown as RealtimeSessionDocument;
    const client = new RealtimeClient({
      exchangeSdp: vi.fn(async () => outcomeUnknown),
      activate: vi.fn(),
      createPeer: () => peer as unknown as RTCPeerConnection,
      getUserMedia: vi.fn(async () => stream),
      createAudioElement: () => ({ autoplay: false, srcObject: null, play: vi.fn(), pause: vi.fn() }) as unknown as HTMLAudioElement,
    });

    await expect(client.connect()).rejects.toThrow('could not confirm');
    expect(peer.setRemoteDescription).not.toHaveBeenCalled();
    expect(peer.close).toHaveBeenCalledOnce();
    expect(track.stop).toHaveBeenCalledOnce();
  });

  it('aborts ICE gathering and removes its listener on close or target switch', async () => {
    const track = { enabled: true, stop: vi.fn() } as unknown as MediaStreamTrack;
    const stream = { getTracks: () => [track], getAudioTracks: () => [track] } as unknown as MediaStream;
    const peer = new FakePeer();
    peer.iceGatheringState = 'gathering';
    const exchangeSdp = vi.fn();
    const client = new RealtimeClient({
      exchangeSdp, activate: vi.fn(), createPeer: () => peer as unknown as RTCPeerConnection,
      getUserMedia: vi.fn(async () => stream),
      createAudioElement: () => ({ autoplay: false, srcObject: null, play: vi.fn(), pause: vi.fn() }) as unknown as HTMLAudioElement,
    });
    const connecting = client.connect();
    await vi.waitFor(() => expect(peer.localDescription).not.toBeNull());
    client.close();
    await expect(connecting).rejects.toThrow('superseded');
    expect(exchangeSdp).not.toHaveBeenCalled();
    expect(peer.listenerCounts.icegatheringstatechange).toBe(0);
  });
});
