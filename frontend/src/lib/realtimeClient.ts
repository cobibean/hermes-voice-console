import type { RealtimeMediaState, RealtimeSessionDocument } from './realtimeTypes';

export interface RealtimePeerOptions {
  exchangeSdp: (offer: string) => Promise<RealtimeSessionDocument>;
  activate: (session: RealtimeSessionDocument) => Promise<void>;
  onState?: (state: RealtimeMediaState) => void;
  onRemoteStream?: (stream: MediaStream) => void;
  onUntrustedData?: (value: unknown) => void;
  createPeer?: () => RTCPeerConnection;
  getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  createAudioElement?: () => HTMLAudioElement;
  createUntrustedDataChannel?: boolean;
}

function waitForIceGathering(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const listener = () => {
      if (peer.iceGatheringState !== 'complete') return;
      peer.removeEventListener('icegatheringstatechange', listener);
      resolve();
    };
    peer.addEventListener('icegatheringstatechange', listener);
  });
}

function waitForConnected(peer: RTCPeerConnection, signal: AbortSignal, timeoutMs = 15_000): Promise<void> {
  if (peer.connectionState === 'connected') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      peer.removeEventListener('connectionstatechange', listener);
      signal.removeEventListener('abort', aborted);
      reject(new Error('Realtime media connection timed out'));
    }, timeoutMs);
    const cleanup = () => {
      window.clearTimeout(timeout);
      peer.removeEventListener('connectionstatechange', listener);
      signal.removeEventListener('abort', aborted);
    };
    const aborted = () => {
      cleanup();
      reject(new Error('Realtime media connection was superseded'));
    };
    const listener = () => {
      if (peer.connectionState === 'connected') {
        cleanup();
        resolve();
      } else if (peer.connectionState === 'failed' || peer.connectionState === 'closed') {
        cleanup();
        reject(new Error('Realtime media connection failed'));
      }
    };
    peer.addEventListener('connectionstatechange', listener);
    signal.addEventListener('abort', aborted, { once: true });
    listener();
  });
}

/** Owns only browser media. Session policy, tools, and commands never cross this peer. */
export class RealtimeClient {
  private readonly options: RealtimePeerOptions;
  private peer: RTCPeerConnection | null = null;
  private localStream: MediaStream | null = null;
  private remoteAudio: HTMLAudioElement | null = null;
  private connectPromise: Promise<RealtimeSessionDocument> | null = null;
  private session: RealtimeSessionDocument | null = null;
  private generation = 0;
  private abort: AbortController | null = null;

  constructor(options: RealtimePeerOptions) {
    this.options = options;
  }

  get activeSession(): RealtimeSessionDocument | null { return this.session; }
  get isConnected(): boolean { return this.peer?.connectionState === 'connected'; }

  connect(): Promise<RealtimeSessionDocument> {
    if (this.session && this.peer && !['closed', 'failed'].includes(this.peer.connectionState)) {
      return Promise.resolve(this.session);
    }
    if (this.connectPromise) return this.connectPromise;
    const generation = ++this.generation;
    const promise = this.open(generation).finally(() => {
      if (this.connectPromise === promise) this.connectPromise = null;
    });
    this.connectPromise = promise;
    return promise;
  }

  private async open(generation: number): Promise<RealtimeSessionDocument> {
    const abort = new AbortController();
    this.abort?.abort();
    this.abort = abort;
    this.options.onState?.('requesting_microphone');
    const getUserMedia = this.options.getUserMedia
      ?? ((constraints) => navigator.mediaDevices.getUserMedia(constraints));
    const stream = await getUserMedia({ audio: true, video: false });
    if (generation !== this.generation) {
      stream.getTracks().forEach((track) => track.stop());
      throw new Error('Realtime media connection was superseded');
    }
    const peer = this.options.createPeer?.() ?? new RTCPeerConnection();
    this.peer = peer;
    this.localStream = stream;
    stream.getAudioTracks().forEach((track) => peer.addTrack(track, stream));
    const audio = this.options.createAudioElement?.() ?? new Audio();
    audio.autoplay = true;
    this.remoteAudio = audio;
    peer.addEventListener('connectionstatechange', () => {
      if (peer !== this.peer) return;
      if (peer.connectionState === 'failed' || peer.connectionState === 'disconnected') {
        this.options.onState?.('failed');
      }
    });
    peer.addEventListener('track', (event) => {
      if (peer !== this.peer) return;
      const remote = event.streams[0];
      if (!remote) return;
      audio.srcObject = remote;
      this.options.onRemoteStream?.(remote);
      void audio.play().catch(() => undefined);
    });
    if (this.options.createUntrustedDataChannel) {
      const channel = peer.createDataChannel('presentation-events');
      channel.addEventListener('message', (event) => {
        try { this.options.onUntrustedData?.(JSON.parse(String(event.data))); }
        catch { this.options.onUntrustedData?.(String(event.data)); }
      });
    }
    this.options.onState?.('negotiating');
    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await waitForIceGathering(peer);
      const sdp = peer.localDescription?.sdp;
      if (!sdp) throw new Error('Browser did not produce a Realtime SDP offer');
      const session = await this.options.exchangeSdp(sdp);
      if (generation !== this.generation) throw new Error('Realtime media connection was superseded');
      await peer.setRemoteDescription({ type: 'answer', sdp: session.answer_sdp });
      await this.options.activate(session);
      await waitForConnected(peer, abort.signal);
      if (generation !== this.generation) throw new Error('Realtime media connection was superseded');
      this.session = session;
      this.options.onState?.('connected');
      return session;
    } catch (error) {
      if (generation === this.generation) {
        this.options.onState?.('failed');
        this.releasePeer();
      }
      throw error;
    }
  }

  setMuted(muted: boolean): void {
    this.localStream?.getAudioTracks().forEach((track) => { track.enabled = !muted; });
  }

  close(): RealtimeSessionDocument | null {
    this.generation += 1;
    this.abort?.abort();
    this.abort = null;
    const session = this.session;
    this.connectPromise = null;
    this.session = null;
    this.releasePeer();
    this.options.onState?.('closed');
    return session;
  }

  private releasePeer(): void {
    this.localStream?.getTracks().forEach((track) => track.stop());
    this.localStream = null;
    if (this.remoteAudio) {
      this.remoteAudio.pause();
      this.remoteAudio.srcObject = null;
      this.remoteAudio = null;
    }
    this.peer?.close();
    this.peer = null;
  }
}
