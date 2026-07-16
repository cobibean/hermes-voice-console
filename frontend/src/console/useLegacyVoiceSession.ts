import { useCallback, useEffect, useRef, useState } from 'react';
import type { AuthTokenProvider } from '../lib/api';
import { startPcm16Capture, type CaptureSession } from '../lib/capture';
import { PlaybackQueue } from '../lib/playback';
import type { AuthMode, VoiceServerEvent } from '../lib/types';
import { VoiceClient } from '../lib/voiceClient';

export interface LegacyVoiceSession {
  connected: boolean;
  inputLevel: number;
  recordingElapsed: number;
  speechFallbackAvailable: boolean;
  connect: () => Promise<VoiceClient>;
  close: () => void;
  startRecording: (turnId: string) => Promise<void>;
  stopRecording: (turnId: string) => void;
  discardRecording: (turnId: string) => void;
  cancelSpeech: (turnId?: string) => void;
  retrySpeech: () => void;
  unlockSpeech: () => void;
  handlePlaybackEvent: (event: VoiceServerEvent) => void;
  client: () => VoiceClient | null;
}

/** Owns the legacy PCM/STT/TTS transport without changing its Runs semantics. */
export function useLegacyVoiceSession({
  enabled,
  authMode,
  getToken,
  target,
  conversationId,
  speakReplies,
  resumeRunId,
  lastSequence,
  onEvent,
  onError,
}: {
  enabled: boolean;
  authMode: AuthMode;
  getToken: AuthTokenProvider;
  target: string;
  conversationId: string;
  speakReplies: boolean;
  resumeRunId?: string;
  lastSequence?: number;
  onEvent: (event: VoiceServerEvent) => void;
  onError: (message: string) => void;
}): LegacyVoiceSession {
  const [connected, setConnected] = useState(false);
  const [inputLevel, setInputLevel] = useState(0);
  const [recordingElapsed, setRecordingElapsed] = useState(0);
  const [speechFallbackAvailable, setSpeechFallbackAvailable] = useState(false);
  const clientRef = useRef<VoiceClient | null>(null);
  const signatureRef = useRef('');
  const connectingRef = useRef<{ signature: string; promise: Promise<VoiceClient> } | null>(null);
  const captureRef = useRef<CaptureSession | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const elapsedTimerRef = useRef<number | null>(null);
  const generationRef = useRef(0);
  const playbackRef = useRef(new PlaybackQueue(undefined, undefined, setSpeechFallbackAvailable));

  const close = useCallback(() => {
    generationRef.current += 1;
    if (elapsedTimerRef.current !== null) window.clearInterval(elapsedTimerRef.current);
    elapsedTimerRef.current = null;
    startedAtRef.current = null;
    const capture = captureRef.current;
    captureRef.current = null;
    void capture?.stop();
    playbackRef.current.cancel(playbackRef.current.activeTurnId ?? '');
    clientRef.current?.close();
    clientRef.current = null;
    signatureRef.current = '';
    connectingRef.current = null;
    setConnected(false);
    setInputLevel(0);
    setRecordingElapsed(0);
  }, []);

  const connect = useCallback(async () => {
    if (!enabled) throw new Error('Legacy voice mode is not active');
    if (!target || !conversationId) throw new Error('Select a target and session first');
    const signature = `${target}|${conversationId}|${speakReplies}`;
    if (connectingRef.current?.signature === signature) return connectingRef.current.promise;
    if (clientRef.current?.isOpen && signatureRef.current === signature) return clientRef.current;
    close();
    const generation = ++generationRef.current;
    const client = new VoiceClient({
      authMode,
      getToken,
      onEvent,
      onAudio: (chunk) => playbackRef.current.pushChunk(chunk),
      onClose: () => setConnected(false),
      onError,
    });
    clientRef.current = client;
    signatureRef.current = signature;
    const promise = client.connect({ target, conversationId, speakReplies, resumeRunId, lastSequence })
      .then(() => {
        if (generation !== generationRef.current) {
          client.close();
          throw new Error('Legacy voice connection was superseded');
        }
        setConnected(true);
        return client;
      })
      .catch((error: unknown) => {
        if (clientRef.current === client) { clientRef.current = null; signatureRef.current = ''; }
        throw error;
      });
    connectingRef.current = { signature, promise };
    try { return await promise; }
    finally { if (connectingRef.current?.promise === promise) connectingRef.current = null; }
  }, [authMode, close, conversationId, enabled, getToken, lastSequence, onError, onEvent, resumeRunId, speakReplies, target]);

  const stopElapsed = useCallback(() => {
    if (elapsedTimerRef.current !== null) window.clearInterval(elapsedTimerRef.current);
    elapsedTimerRef.current = null;
    startedAtRef.current = null;
  }, []);
  const startRecording = useCallback(async (turnId: string) => {
    void playbackRef.current.unlock();
    const client = await connect();
    await client.startRecording(turnId);
    startedAtRef.current = Date.now();
    elapsedTimerRef.current = window.setInterval(() => {
      setRecordingElapsed((Date.now() - (startedAtRef.current ?? Date.now())) / 1000);
    }, 100);
    try {
      captureRef.current = await startPcm16Capture((chunk) => client.sendAudio(chunk), setInputLevel);
    } catch (error) {
      stopElapsed();
      if (client.isOpen) client.cancelRecording(turnId);
      throw error;
    }
  }, [connect, stopElapsed]);
  const stopRecording = useCallback((turnId: string) => {
    stopElapsed();
    const capture = captureRef.current;
    captureRef.current = null;
    void capture?.stop().finally(() => {
      if (clientRef.current?.isOpen) clientRef.current.stopRecording(turnId);
    });
  }, [stopElapsed]);
  const discardRecording = useCallback((turnId: string) => {
    stopElapsed();
    setInputLevel(0);
    setRecordingElapsed(0);
    const capture = captureRef.current;
    captureRef.current = null;
    void capture?.stop().finally(() => {
      if (clientRef.current?.isOpen) clientRef.current.cancelRecording(turnId);
    });
    if (!capture && clientRef.current?.isOpen) clientRef.current.cancelRecording(turnId);
  }, [stopElapsed]);
  const cancelSpeech = useCallback((turnId = '') => {
    const active = playbackRef.current.activeTurnId ?? turnId;
    playbackRef.current.cancel(active);
    if (active) clientRef.current?.cancelTts(active);
  }, []);
  const retrySpeech = useCallback(() => { void playbackRef.current.retry(); }, []);
  const unlockSpeech = useCallback(() => { void playbackRef.current.unlock(); }, []);
  const handlePlaybackEvent = useCallback((event: VoiceServerEvent) => {
    if (event.type === 'tts.start') playbackRef.current.start(event.turn_id, event.chunk_index, event.mime);
    if (event.type === 'tts.end') playbackRef.current.end(event.turn_id, event.chunk_index);
    if (event.type === 'tts.complete') playbackRef.current.complete(event.turn_id);
    if (event.type === 'tts.cancelled') playbackRef.current.cancel(event.turn_id);
  }, []);

  useEffect(() => () => { close(); }, [close]);

  return {
    connected, inputLevel, recordingElapsed, speechFallbackAvailable,
    connect, close, startRecording, stopRecording, discardRecording,
    cancelSpeech, retrySpeech, unlockSpeech, handlePlaybackEvent, client: () => clientRef.current,
  };
}
