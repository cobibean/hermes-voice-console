import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { PendingApproval } from '../components/ApprovalModal';
import { createSession, listSessions, type AuthTokenProvider } from '../lib/api';
import { browserSupportsCapture, startPcm16Capture, type CaptureSession } from '../lib/capture';
import { PlaybackQueue } from '../lib/playback';
import { clearRecovery, loadRecovery, saveRecovery } from '../lib/recovery';
import { consoleReducer, initialConsoleState, nextTurnId } from '../lib/state';
import type { AuthMode, Bootstrap, SessionInfo, TimelineItem, VoiceServerEvent } from '../lib/types';
import { VoiceClient } from '../lib/voiceClient';
import { deriveConsoleViewState } from './viewState';

type ApprovalDecision = 'once' | 'session' | 'always' | 'deny';

function timelineMessage(event: VoiceServerEvent): string {
  switch (event.type) {
    case 'transcript.final': return event.text;
    case 'agent.delta': return event.delta;
    case 'agent.completed': return event.text;
    case 'agent.approval.request': return String(event.approval.message ?? 'Approval requested');
    case 'error': return event.message;
    default: return event.type;
  }
}

function approvalChoices(payload: Record<string, unknown>): ApprovalDecision[] {
  const raw = payload.choices;
  const allowed = new Set<ApprovalDecision>(['once', 'session', 'always', 'deny']);
  if (Array.isArray(raw)) {
    const choices = raw.filter(
      (item): item is ApprovalDecision => typeof item === 'string' && allowed.has(item as ApprovalDecision),
    );
    if (choices.length > 0) return choices;
  }
  return ['once', 'session', 'always', 'deny'];
}

function hasRunId(event: VoiceServerEvent): event is VoiceServerEvent & { run_id: string } {
  return 'run_id' in event && typeof event.run_id === 'string';
}

function hasTurnId(event: VoiceServerEvent): event is VoiceServerEvent & { turn_id: string } {
  return 'turn_id' in event && typeof event.turn_id === 'string';
}

export interface ConsoleController {
  acceptanceUnknown: {
    kind: 'acceptance_unknown' | 'unrecoverable';
    id: string;
    message: string;
  } | null;
  acknowledgeAcceptanceUnknown: () => void;
  approval: PendingApproval | null;
  bootstrap: Bootstrap | null;
  cancelSpeech: () => void;
  closeClient: () => void;
  connect: () => Promise<VoiceClient>;
  connected: boolean;
  isCaptureSupported: boolean;
  loadError?: string;
  response: string;
  inputLevel: number;
  recordingElapsed: number;
  speechFallbackAvailable: boolean;
  retrySpeech: () => void;
  textDraft: string;
  setTextDraft: (value: string) => void;
  submitText: () => Promise<void>;
  sessions: SessionInfo[];
  newConversation: () => Promise<void>;
  resolveApproval: (decision: ApprovalDecision) => void;
  selectSession: (value: string) => void;
  selectTarget: (name: string) => void;
  selectedTarget: string;
  sessionKey: string;
  setSpeakReplies: (value: boolean) => void;
  speakReplies: boolean;
  startRecording: () => Promise<void>;
  state: typeof initialConsoleState;
  stopRecording: () => void;
  discardRecording: () => void;
  stopRun: () => void;
  timeline: TimelineItem[];
  transcript: string;
  viewState: ReturnType<typeof deriveConsoleViewState>;
}

export function useConsoleController({
  authMode,
  getToken,
  bootstrap,
  loadError,
}: {
  authMode: AuthMode;
  getToken: AuthTokenProvider;
  bootstrap: Bootstrap | null;
  loadError?: string;
}): ConsoleController {
  const [selectedTarget, setSelectedTarget] = useState('');
  const [sessionKey, setSessionKey] = useState('');
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [speakReplies, setSpeakRepliesState] = useState(false);
  const [state, dispatch] = useReducer(consoleReducer, initialConsoleState);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');
  const [textDraft, setTextDraft] = useState('');
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [acceptanceUnknown, setAcceptanceUnknown] = useState<{
    kind: 'acceptance_unknown' | 'unrecoverable';
    id: string;
    message: string;
  } | null>(null);
  const [connected, setConnected] = useState(false);
  const [inputLevel, setInputLevel] = useState(0);
  const [recordingElapsed, setRecordingElapsed] = useState(0);
  const [speechFallbackAvailable, setSpeechFallbackAvailable] = useState(false);
  const clientRef = useRef<VoiceClient | null>(null);
  const clientSignatureRef = useRef('');
  const captureRef = useRef<CaptureSession | null>(null);
  const playbackRef = useRef(new PlaybackQueue(
    undefined,
    undefined,
    setSpeechFallbackAvailable,
  ));
  const stopRequestedRef = useRef(false);
  const discardRequestedRef = useRef(false);
  const activeRunIdRef = useRef<string | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);
  const lastSequenceRef = useRef(0);
  const pendingTextTurnRef = useRef<string | null>(null);

  const closeClient = useCallback(() => {
    clientRef.current?.close();
    clientRef.current = null;
    clientSignatureRef.current = '';
    setConnected(false);
  }, []);

  useEffect(() => () => {
    closeClient();
    void captureRef.current?.stop();
    playbackRef.current.cancel(playbackRef.current.activeTurnId ?? '');
  }, [closeClient]);

  useEffect(() => {
    if (state.recording !== 'recording') {
      setInputLevel(0);
      if (state.recording === 'idle') setRecordingElapsed(0);
      return undefined;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => setRecordingElapsed((Date.now() - startedAt) / 1000), 100);
    return () => window.clearInterval(timer);
  }, [state.recording]);

  useEffect(() => {
    const first = bootstrap?.targets[0];
    if (!first) return;
    setSelectedTarget((current) => current || first.name);
    setSpeakRepliesState(bootstrap.voice.speak_replies_default);
  }, [bootstrap]);

  useEffect(() => {
    let active = true;
    if (!selectedTarget) return undefined;
    void listSessions(selectedTarget, getToken)
      .then(async (owned) => {
        if (!active) return;
        const available = owned.length > 0 ? owned : [await createSession(selectedTarget, getToken)];
        if (!active) return;
        setSessions(available);
        setSessionKey((current) => current || available[0].conversation_id);
      })
      .catch((error: unknown) => dispatch({ type: 'error', message: (error as Error).message }));
    return () => {
      active = false;
    };
  }, [getToken, selectedTarget]);

  const appendEvent = useCallback((event: VoiceServerEvent) => {
    setTimeline((items) => [
      ...items,
      {
        id: `${Date.now()}-${items.length}`,
        ts: Date.now(),
        kind: event.type,
        message: timelineMessage(event),
        payload: event,
      },
    ].slice(-100));
  }, []);

  const handleEvent = useCallback((event: VoiceServerEvent) => {
    if (
      hasRunId(event)
      && activeRunIdRef.current
      && event.type !== 'agent.run.started'
      && event.run_id !== activeRunIdRef.current
    ) return;
    if (hasTurnId(event) && activeTurnIdRef.current && event.turn_id !== activeTurnIdRef.current) return;
    appendEvent(event);
    dispatch({ type: 'event', event });
    if (event.type === 'ready') setConnected(true);
    if (event.type === 'recording.started') activeTurnIdRef.current = event.turn_id;
    if (event.type === 'transcript.final') setTranscript(event.text);
    if (event.type === 'agent.run.started') {
      activeRunIdRef.current = event.run_id;
      lastSequenceRef.current = 'sequence' in event && typeof event.sequence === 'number' ? event.sequence : 0;
      saveRecovery({
        target: selectedTarget,
        conversationId: sessionKey,
        runId: event.run_id,
        lastSequence: lastSequenceRef.current,
      });
      setResponse('');
      setApproval(null);
      if (pendingTextTurnRef.current === event.turn_id) {
        setTextDraft('');
        pendingTextTurnRef.current = null;
      }
    }
    if (event.type === 'agent.delta') setResponse((previous) => previous + event.delta);
    if (event.type === 'agent.completed') setResponse(event.text);
    if (event.type === 'agent.approval.request') {
      setApproval({
        runId: event.run_id,
        message: String(event.approval.message ?? 'Hermes needs approval to continue.'),
        choices: approvalChoices(event.approval),
        payload: event.approval,
      });
    }
    if (event.type === 'run.acceptance_unknown') {
      setAcceptanceUnknown({
        kind: 'acceptance_unknown',
        id: event.local_turn_id,
        message: event.message,
      });
    }
    if (event.type === 'run.acceptance_unknown.acknowledged') setAcceptanceUnknown(null);
    if (event.type === 'run.unrecoverable') {
      setAcceptanceUnknown({ kind: 'unrecoverable', id: event.run_id, message: event.error });
    }
    if (event.type === 'run.unrecoverable.acknowledged') setAcceptanceUnknown(null);
    if (event.type === 'run.snapshot' && event.status === 'unrecoverable') {
      setAcceptanceUnknown({
        kind: 'unrecoverable',
        id: event.run_id,
        message: 'Hermes no longer exposes this run; acknowledgement is required.',
      });
    }
    if (event.type === 'agent.approval.resolved' || event.type === 'agent.approval.responded') setApproval(null);
    if ('sequence' in event && typeof event.sequence === 'number' && activeRunIdRef.current) {
      lastSequenceRef.current = event.sequence;
      saveRecovery({
        target: selectedTarget,
        conversationId: sessionKey,
        runId: activeRunIdRef.current,
        lastSequence: event.sequence,
      });
    }
    if (event.type === 'agent.failed' || event.type === 'agent.stopped' || event.type === 'agent.completed') {
      activeRunIdRef.current = null;
      clearRecovery();
    }
    if (event.type === 'tts.start') playbackRef.current.start(event.turn_id, event.chunk_index, event.mime);
    if (event.type === 'tts.end') playbackRef.current.end(event.turn_id, event.chunk_index);
    if (event.type === 'tts.complete') playbackRef.current.complete(event.turn_id);
    if (event.type === 'tts.cancelled') playbackRef.current.cancel(event.turn_id);
  }, [appendEvent, selectedTarget, sessionKey]);

  const connect = useCallback(async () => {
    if (!selectedTarget || !sessionKey) throw new Error('Select a target and session first');
    const signature = `${selectedTarget}|${sessionKey}|${speakReplies}`;
    if (clientRef.current?.isOpen && clientSignatureRef.current === signature) return clientRef.current;
    closeClient();
    const client = new VoiceClient({
      authMode,
      getToken,
      onEvent: handleEvent,
      onAudio: (chunk) => playbackRef.current.pushChunk(chunk),
      onClose: () => setConnected(false),
      onError: (message) => dispatch({ type: 'error', message }),
    });
    const recovery = loadRecovery();
    const canResume = recovery?.target === selectedTarget && recovery.conversationId === sessionKey;
    await client.connect({
      target: selectedTarget,
      conversationId: sessionKey,
      speakReplies,
      resumeRunId: canResume ? recovery.runId : undefined,
      lastSequence: canResume ? recovery.lastSequence : undefined,
    });
    clientRef.current = client;
    clientSignatureRef.current = signature;
    return client;
  }, [authMode, closeClient, getToken, handleEvent, selectedTarget, sessionKey, speakReplies]);

  const startRecording = useCallback(async () => {
    const turnId = nextTurnId();
    stopRequestedRef.current = false;
    discardRequestedRef.current = false;
    void playbackRef.current.unlock();
    activeTurnIdRef.current = turnId;
    dispatch({ type: 'recording.start', turnId });
    try {
      const client = await connect();
      await client.startRecording(turnId);
      if (discardRequestedRef.current) {
        client.cancelRecording(turnId);
        dispatch({ type: 'recording.discard' });
        return;
      }
      if (stopRequestedRef.current) {
        client.stopRecording(turnId);
        dispatch({ type: 'recording.stop' });
        return;
      }
      const capture = await startPcm16Capture((chunk) => client.sendAudio(chunk), setInputLevel);
      captureRef.current = capture;
      if (stopRequestedRef.current) {
        client.stopRecording(turnId);
        dispatch({ type: 'recording.stop' });
        await capture.stop();
        captureRef.current = null;
      }
    } catch (error) {
      dispatch({ type: 'error', message: (error as Error).message });
      await captureRef.current?.stop();
      captureRef.current = null;
    }
  }, [connect]);

  const submitText = useCallback(async () => {
    const text = textDraft.trim();
    if (!text) return;
    const turnId = nextTurnId();
    activeTurnIdRef.current = turnId;
    pendingTextTurnRef.current = turnId;
    try {
      const client = await connect();
      client.sendText(turnId, text);
    } catch (error) {
      pendingTextTurnRef.current = null;
      dispatch({ type: 'error', message: (error as Error).message });
    }
  }, [connect, textDraft]);

  const stopRecording = useCallback(() => {
    const turnId = activeTurnIdRef.current ?? state.activeTurnId;
    if (state.recording === 'connecting') {
      stopRequestedRef.current = true;
      return;
    }
    if (!turnId || state.recording === 'idle') return;
    dispatch({ type: 'recording.stop' });
    clientRef.current?.stopRecording(turnId);
    void captureRef.current?.stop();
    captureRef.current = null;
  }, [state.activeTurnId, state.recording]);

  const discardRecording = useCallback(() => {
    const turnId = activeTurnIdRef.current ?? state.activeTurnId;
    discardRequestedRef.current = true;
    stopRequestedRef.current = false;
    dispatch({ type: 'recording.discard' });
    void captureRef.current?.stop();
    captureRef.current = null;
    setInputLevel(0);
    if (turnId && clientRef.current?.isOpen) clientRef.current.cancelRecording(turnId);
  }, [state.activeTurnId]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden' && (state.recording === 'recording' || state.recording === 'connecting')) {
        discardRecording();
      }
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted || !clientRef.current?.isOpen) void connect().catch(() => undefined);
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [connect, discardRecording, state.recording]);

  const cancelSpeech = useCallback(() => {
    const turnId = playbackRef.current.activeTurnId ?? activeTurnIdRef.current ?? '';
    playbackRef.current.cancel(turnId);
    if (turnId) clientRef.current?.cancelTts(turnId);
    dispatch({ type: 'playback.cancel' });
  }, []);

  const retrySpeech = useCallback(() => {
    void playbackRef.current.retry();
  }, []);

  const setSpeakReplies = useCallback((value: boolean) => {
    if (!value) cancelSpeech();
    if (value) void playbackRef.current.unlock();
    if (value !== speakReplies) closeClient();
    setSpeakRepliesState(value);
  }, [cancelSpeech, closeClient, speakReplies]);

  const resolveApproval = useCallback((decision: ApprovalDecision) => {
    if (!approval) return;
    setApproval({ ...approval, submitting: true });
    clientRef.current?.resolveApproval(approval.runId, decision);
  }, [approval]);

  const stopRun = useCallback(() => {
    if (state.activeRunId) clientRef.current?.stopRun(state.activeRunId);
  }, [state.activeRunId]);

  const acknowledgeAcceptanceUnknown = useCallback(() => {
    if (!acceptanceUnknown) return;
    if (acceptanceUnknown.kind === 'acceptance_unknown') {
      clientRef.current?.acknowledgeAcceptanceUnknown(acceptanceUnknown.id);
    } else {
      clientRef.current?.acknowledgeUnrecoverable(acceptanceUnknown.id);
    }
  }, [acceptanceUnknown]);

  const selectTarget = useCallback((name: string) => {
    clearRecovery();
    setSelectedTarget(name);
    setSessionKey('');
    setSessions([]);
    closeClient();
  }, [closeClient]);

  const selectSession = useCallback((value: string) => {
    clearRecovery();
    setSessionKey(value);
    closeClient();
  }, [closeClient]);

  const newConversation = useCallback(async () => {
    if (!selectedTarget) return;
    const created = await createSession(selectedTarget, getToken);
    clearRecovery();
    setSessions((current) => [created, ...current]);
    setSessionKey(created.conversation_id);
    closeClient();
  }, [closeClient, getToken, selectedTarget]);

  return useMemo(() => ({
    acceptanceUnknown,
    acknowledgeAcceptanceUnknown,
    approval,
    bootstrap,
    cancelSpeech,
    closeClient,
    connect,
    connected,
    discardRecording,
    inputLevel,
    isCaptureSupported: browserSupportsCapture(),
    loadError,
    newConversation,
    response,
    recordingElapsed,
    retrySpeech,
    resolveApproval,
    selectSession,
    selectTarget,
    selectedTarget,
    sessionKey,
    sessions,
    setTextDraft,
    setSpeakReplies,
    speakReplies,
    speechFallbackAvailable,
    startRecording,
    state,
    submitText,
    stopRecording,
    stopRun,
    timeline,
    textDraft,
    transcript,
    viewState: deriveConsoleViewState(state, connected),
  }), [
    acceptanceUnknown,
    acknowledgeAcceptanceUnknown,
    approval,
    bootstrap,
    cancelSpeech,
    closeClient,
    connect,
    connected,
    discardRecording,
    inputLevel,
    loadError,
    newConversation,
    response,
    recordingElapsed,
    retrySpeech,
    resolveApproval,
    selectSession,
    selectTarget,
    selectedTarget,
    sessionKey,
    sessions,
    setSpeakReplies,
    speakReplies,
    speechFallbackAvailable,
    startRecording,
    state,
    submitText,
    stopRecording,
    stopRun,
    timeline,
    textDraft,
    transcript,
  ]);
}
