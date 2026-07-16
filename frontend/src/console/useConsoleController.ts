import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { PendingApproval } from '../components/ApprovalModal';
import { createSession, listSessions, loadSessionMessages, type AuthTokenProvider } from '../lib/api';
import { browserSupportsCapture } from '../lib/capture';
import { clearRecovery, loadRecovery, saveRecovery } from '../lib/recovery';
import { consoleReducer, initialConsoleState, nextTurnId } from '../lib/state';
import type { AuthMode, Bootstrap, ConversationMessage, SessionInfo, TimelineItem, VoiceServerEvent } from '../lib/types';
import type { VoiceClient } from '../lib/voiceClient';
import { deriveConsoleViewState } from './viewState';
import { voiceDiagnostic } from '../lib/diagnostics';
import type { VoiceTransport } from '../lib/realtimeTypes';
import { useLegacyVoiceSession } from './useLegacyVoiceSession';
import { useRealtimeSession } from './useRealtimeSession';
import { describeRealtimeApproval, presentRealtimeJobs, realtimeReadiness, workerControlPayload } from './buildRealtimePresentation';
import type { RealtimePresentationModel } from './realtimePresentation';
import { mergeConversationMessages } from './conversationProjection';

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
  connect: () => Promise<VoiceClient | void>;
  connected: boolean;
  isCaptureSupported: boolean;
  loadError?: string;
  response: string;
  messages: ConversationMessage[];
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
  transport: VoiceTransport;
  setTransport: (transport: VoiceTransport) => void;
  realtime: RealtimePresentationModel;
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
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [textDraft, setTextDraft] = useState('');
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [acceptanceUnknown, setAcceptanceUnknown] = useState<{
    kind: 'acceptance_unknown' | 'unrecoverable';
    id: string;
    message: string;
  } | null>(null);
  const [transport, setTransportState] = useState<VoiceTransport>('legacy');
  const handleEventRef = useRef<(event: VoiceServerEvent) => void>(() => undefined);
  const stopRequestedRef = useRef(false);
  const discardRequestedRef = useRef(false);
  const activeRunIdRef = useRef<string | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);
  const lastSequenceRef = useRef(0);
  const pendingTextTurnRef = useRef<{ turnId: string; text: string } | null>(null);
  const feedSequenceRef = useRef(0);
  const controllerEpochRef = useRef(0);
  const conversationIdentity = `${selectedTarget}|${sessionKey}`;
  const historyIdentityRef = useRef('');
  const selectedTargetConfig = bootstrap?.targets.find((target) => target.name === selectedTarget);
  const recovery = loadRecovery();
  const dispatchError = useCallback((message: string) => dispatch({ type: 'error', message }), []);
  const forwardLegacyEvent = useCallback((event: VoiceServerEvent) => handleEventRef.current(event), []);
  const legacySession = useLegacyVoiceSession({
    enabled: transport === 'legacy',
    authMode,
    getToken,
    target: selectedTarget,
    conversationId: sessionKey,
    speakReplies,
    resumeRunId: recovery?.target === selectedTarget && recovery.conversationId === sessionKey ? recovery.runId : undefined,
    lastSequence: recovery?.target === selectedTarget && recovery.conversationId === sessionKey ? recovery.lastSequence : undefined,
    onEvent: forwardLegacyEvent,
    onError: dispatchError,
  });
  const realtimeSession = useRealtimeSession({
    enabled: transport === 'realtime' && Boolean(selectedTargetConfig?.realtime_enabled),
    target: selectedTarget,
    conversationId: sessionKey,
    getToken,
  });

  const closeClient = useCallback(() => {
    controllerEpochRef.current += 1;
    legacySession.close();
    realtimeSession.close();
  }, [legacySession.close, realtimeSession.close]);

  const runOwnedRealtimeOperation = useCallback((operation: () => Promise<void>) => {
    const epoch = controllerEpochRef.current;
    const owner = conversationIdentity;
    let pending: Promise<void>;
    try { pending = operation(); }
    catch (error) { pending = Promise.reject(error); }
    void pending.catch((error: unknown) => {
      if (controllerEpochRef.current !== epoch || `${selectedTarget}|${sessionKey}` !== owner) return;
      dispatch({ type: 'error', message: (error as Error).message });
    });
  }, [conversationIdentity, selectedTarget, sessionKey]);

  useEffect(() => {
    const first = bootstrap?.targets[0];
    if (!first) return;
    setSelectedTarget((current) => current || first.name);
    setSpeakRepliesState(bootstrap.voice.speak_replies_default);
    setTransportState(first.realtime_enabled ? 'realtime' : 'legacy');
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

  useEffect(() => {
    let active = true;
    setMessages([]);
    setResponse('');
    setTranscript('');
    if (!selectedTarget || !sessionKey) return undefined;
    void loadSessionMessages(sessionKey, selectedTarget, getToken)
      .then((history) => {
        if (!active) return;
        historyIdentityRef.current = `${selectedTarget}|${sessionKey}`;
        setMessages(history);
        voiceDiagnostic('history.loaded', {
          target: selectedTarget,
          conversationId: sessionKey,
          messages: history.length,
        });
        const lastUser = [...history].reverse().find((message) => message.role === 'user');
        setTranscript(lastUser?.content ?? '');
      })
      .catch((error: unknown) => dispatch({ type: 'error', message: (error as Error).message }));
    return () => { active = false; };
  }, [getToken, selectedTarget, sessionKey]);

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
    if (event.type === 'recording.started') activeTurnIdRef.current = event.turn_id;
    if (event.type === 'transcript.final') {
      historyIdentityRef.current = conversationIdentity;
      setTranscript(event.text);
      setMessages((current) => [...current, { role: 'user', content: event.text }]);
      setResponse('');
    }
    if (event.type === 'text.accepted' && pendingTextTurnRef.current?.turnId === event.turn_id) {
      historyIdentityRef.current = conversationIdentity;
      setMessages((current) => [...current, { role: 'user', content: pendingTextTurnRef.current!.text }]);
      setResponse('');
    }
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
      if (pendingTextTurnRef.current?.turnId === event.turn_id) {
        setTextDraft('');
        pendingTextTurnRef.current = null;
      }
    }
    if (event.type === 'agent.delta') setResponse((previous) => previous + event.delta);
    if (event.type === 'agent.tool.started') {
      historyIdentityRef.current = conversationIdentity;
      feedSequenceRef.current += 1;
      const id = `tool-${event.run_id}-${feedSequenceRef.current}`;
      setMessages((current) => [...current, {
        role: 'tool',
        id,
        runId: event.run_id,
        tool: event.tool ?? 'Hermes tool',
        content: event.preview || 'Tool call started',
        status: 'running',
      }]);
    }
    if (event.type === 'agent.tool.completed') {
      historyIdentityRef.current = conversationIdentity;
      setMessages((current) => {
        const next = [...current];
        let index = -1;
        for (let cursor = next.length - 1; cursor >= 0; cursor -= 1) {
          const message = next[cursor];
          if (
            message.role === 'tool'
            && message.runId === event.run_id
            && message.status === 'running'
            && (!event.tool || message.tool === event.tool)
          ) {
            index = cursor;
            break;
          }
        }
        if (index >= 0) {
          next[index] = {
            ...next[index],
            status: event.error ? 'failed' : 'completed',
            duration: event.duration,
          };
        } else {
          feedSequenceRef.current += 1;
          next.push({
            role: 'tool',
            id: `tool-${event.run_id}-${feedSequenceRef.current}`,
            runId: event.run_id,
            tool: event.tool ?? 'Hermes tool',
            content: 'Tool call completed',
            status: event.error ? 'failed' : 'completed',
            duration: event.duration,
          });
        }
        return next;
      });
    }
    if (event.type === 'agent.completed') {
      historyIdentityRef.current = conversationIdentity;
      setMessages((current) => [...current, { role: 'assistant', content: event.text }]);
      setResponse('');
    }
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
      setApproval(null);
      clearRecovery();
    }
    legacySession.handlePlaybackEvent(event);
  }, [appendEvent, conversationIdentity, legacySession.handlePlaybackEvent, selectedTarget, sessionKey]);
  handleEventRef.current = handleEvent;

  const connect = useCallback(async () => {
    if (!selectedTarget || !sessionKey) throw new Error('Select a target and session first');
    if (transport === 'realtime') return realtimeSession.connect();
    return legacySession.connect();
  }, [legacySession.connect, realtimeSession.connect, selectedTarget, sessionKey, transport]);

  useEffect(() => {
    if (!selectedTarget || !sessionKey || transport !== 'legacy') return;
    void connect().catch((error: unknown) => {
      voiceDiagnostic('socket.autoconnect.failed', {
        error: error instanceof Error ? error.message : 'unknown connection error',
      });
    });
  }, [connect, selectedTarget, sessionKey, transport]);

  const startRecording = useCallback(async () => {
    const turnId = nextTurnId();
    stopRequestedRef.current = false;
    discardRequestedRef.current = false;
    activeTurnIdRef.current = turnId;
    dispatch({ type: 'recording.start', turnId });
    try {
      if (transport === 'realtime') {
        await realtimeSession.connect();
        realtimeSession.startManualTurn();
        return;
      }
      await legacySession.startRecording(turnId);
      if (discardRequestedRef.current) {
        legacySession.discardRecording(turnId);
        dispatch({ type: 'recording.discard' });
        return;
      }
      if (stopRequestedRef.current) {
        legacySession.stopRecording(turnId);
        dispatch({ type: 'recording.stop' });
      }
    } catch (error) {
      dispatch({ type: 'error', message: (error as Error).message });
    }
  }, [legacySession.discardRecording, legacySession.startRecording, legacySession.stopRecording, realtimeSession.connect, realtimeSession.startManualTurn, transport]);

  const submitText = useCallback(async () => {
    const text = textDraft.trim();
    if (!text) return;
    const turnId = nextTurnId();
    activeTurnIdRef.current = turnId;
    pendingTextTurnRef.current = { turnId, text };
    try {
      if (transport === 'realtime') {
        await realtimeSession.connect();
        await realtimeSession.sendInput(text);
        historyIdentityRef.current = conversationIdentity;
        setMessages((current) => [...current, { role: 'user', content: text }]);
        setTextDraft('');
        pendingTextTurnRef.current = null;
      } else {
        const client = await legacySession.connect();
        client.sendText(turnId, text);
      }
    } catch (error) {
      pendingTextTurnRef.current = null;
      dispatch({ type: 'error', message: (error as Error).message });
    }
  }, [conversationIdentity, legacySession.connect, realtimeSession.connect, realtimeSession.sendInput, textDraft, transport]);

  const stopRecording = useCallback(() => {
    const turnId = activeTurnIdRef.current ?? state.activeTurnId;
    if (!turnId || state.recording === 'idle') return;
    stopRequestedRef.current = true;
    dispatch({ type: 'recording.stop' });
    if (transport === 'realtime') {
      realtimeSession.stopManualTurn();
      runOwnedRealtimeOperation(realtimeSession.commitManualTurn);
    }
    else legacySession.stopRecording(turnId);
  }, [legacySession.stopRecording, realtimeSession.commitManualTurn, realtimeSession.stopManualTurn, runOwnedRealtimeOperation, state.activeTurnId, state.recording, transport]);

  const discardRecording = useCallback(() => {
    const turnId = activeTurnIdRef.current ?? state.activeTurnId;
    discardRequestedRef.current = true;
    stopRequestedRef.current = false;
    dispatch({ type: 'recording.discard' });
    if (transport === 'realtime') realtimeSession.discardManualTurn();
    else if (turnId) legacySession.discardRecording(turnId);
  }, [legacySession.discardRecording, realtimeSession.discardManualTurn, state.activeTurnId, transport]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'hidden' && (state.recording === 'recording' || state.recording === 'connecting')) {
        discardRecording();
      }
    };
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) void connect().catch(() => undefined);
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pageshow', onPageShow);
    };
  }, [connect, discardRecording, state.recording]);

  const cancelSpeech = useCallback(() => {
    if (transport === 'realtime') {
      void realtimeSession.interruptSpeech()
        .catch((error: unknown) => dispatch({ type: 'error', message: (error as Error).message }));
    }
    else legacySession.cancelSpeech(activeTurnIdRef.current ?? '');
    dispatch({ type: 'playback.cancel' });
  }, [legacySession.cancelSpeech, realtimeSession.interruptSpeech, transport]);

  const retrySpeech = useCallback(() => {
    legacySession.retrySpeech();
  }, [legacySession.retrySpeech]);

  const setSpeakReplies = useCallback((value: boolean) => {
    if (!value) cancelSpeech();
    if (value) legacySession.unlockSpeech();
    if (value !== speakReplies) closeClient();
    setSpeakRepliesState(value);
  }, [cancelSpeech, closeClient, legacySession.unlockSpeech, speakReplies]);

  const realtimeApproval = useMemo<PendingApproval | null>(() => {
    const pending = Object.values(realtimeSession.projection.approvals).find((item) => (
      ['pending', 'resolving'].includes(String(item.state))
    ));
    if (!pending || typeof pending.approval_id !== 'string') return null;
    return {
      runId: pending.approval_id,
      message: describeRealtimeApproval(pending, realtimeSession.projection.toolCalls),
      choices: approvalChoices(pending),
      payload: pending,
      submitting: pending.state === 'resolving' || realtimeSession.submittingApprovalId === pending.approval_id,
    };
  }, [realtimeSession.projection.approvals, realtimeSession.projection.toolCalls, realtimeSession.submittingApprovalId]);

  const resolveApproval = useCallback((decision: ApprovalDecision) => {
    if (transport === 'realtime') {
      if (!realtimeApproval) return;
      void realtimeSession.resolveApproval(realtimeApproval.runId, decision)
        .catch((error: unknown) => dispatch({ type: 'error', message: (error as Error).message }));
      return;
    }
    if (!approval) return;
    setApproval({ ...approval, submitting: true });
    legacySession.client()?.resolveApproval(approval.runId, decision);
  }, [approval, legacySession, realtimeApproval, realtimeSession, transport]);

  const stopRun = useCallback(() => {
    if (state.activeRunId) legacySession.client()?.stopRun(state.activeRunId);
  }, [legacySession, state.activeRunId]);

  const acknowledgeAcceptanceUnknown = useCallback(() => {
    if (!acceptanceUnknown) return;
    if (acceptanceUnknown.kind === 'acceptance_unknown') {
      legacySession.client()?.acknowledgeAcceptanceUnknown(acceptanceUnknown.id);
    } else {
      legacySession.client()?.acknowledgeUnrecoverable(acceptanceUnknown.id);
    }
  }, [acceptanceUnknown, legacySession]);

  const selectTarget = useCallback((name: string) => {
    clearRecovery();
    setSelectedTarget(name);
    setSessionKey('');
    setSessions([]);
    closeClient();
    const target = bootstrap?.targets.find((item) => item.name === name);
    setTransportState(target?.realtime_enabled ? 'realtime' : 'legacy');
  }, [bootstrap?.targets, closeClient]);

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

  const setTransport = useCallback((next: VoiceTransport) => {
    if (next === 'realtime' && !selectedTargetConfig?.realtime_enabled) return;
    closeClient();
    setTransportState(next);
  }, [closeClient, selectedTargetConfig?.realtime_enabled]);

  const connected = transport === 'realtime' ? realtimeSession.connected : legacySession.connected;
  const inputLevel = transport === 'realtime' ? 0 : legacySession.inputLevel;
  const recordingElapsed = transport === 'realtime' ? 0 : legacySession.recordingElapsed;
  const speechFallbackAvailable = transport === 'legacy' && legacySession.speechFallbackAvailable;
  const identityBoundHistory = historyIdentityRef.current === conversationIdentity ? messages : [];
  const projectedMessages = transport === 'realtime'
    ? mergeConversationMessages(identityBoundHistory, realtimeSession.projection.messages)
    : identityBoundHistory;
  const artifactAllowedOrigins = [window.location.origin];
  const runWorkerCommand = (jobId: string, operation: 'refine' | 'redirect' | 'cancel', payload: Record<string, unknown> = {}) => {
    const job = realtimeSession.projection.workerJobs[jobId];
    const revision = job?.revision;
    if (typeof revision !== 'number') {
      dispatch({ type: 'error', message: 'Worker state is missing its current revision. Reconnect before controlling it.' });
      return;
    }
    void realtimeSession.workerCommand(jobId, operation, revision, payload)
      .catch((error: unknown) => dispatch({ type: 'error', message: (error as Error).message }));
  };
  const sendManualTurn = useCallback(() => {
    realtimeSession.stopManualTurn();
    if (state.recording !== 'idle') dispatch({ type: 'recording.stop' });
    runOwnedRealtimeOperation(realtimeSession.commitManualTurn);
  }, [realtimeSession.commitManualTurn, realtimeSession.stopManualTurn, runOwnedRealtimeOperation, state.recording]);
  const discardManualTurn = useCallback(() => {
    runOwnedRealtimeOperation(realtimeSession.discardManualTurn);
  }, [realtimeSession.discardManualTurn, runOwnedRealtimeOperation]);
  const endRealtimeCall = useCallback(() => {
    controllerEpochRef.current += 1;
    realtimeSession.close();
  }, [realtimeSession.close]);
  const manualCaptureActive = ['starting', 'capturing', 'committing', 'discarding']
    .includes(realtimeSession.manualCaptureState);
  const realtime = useMemo<RealtimePresentationModel>(() => ({
    mode: transport,
    readiness: transport === 'legacy' ? 'disconnected' : realtimeReadiness(realtimeSession),
    readinessDetail: transport === 'realtime' ? realtimeSession.stateDetail : undefined,
    canReconnect: transport === 'realtime' && ['disconnected', 'failed', 'degraded'].includes(realtimeSession.state),
    muted: realtimeSession.muted,
    manualTurnTaking: realtimeSession.manualTurnTaking,
    manualCaptureState: realtimeSession.manualCaptureState,
    manualCaptureError: realtimeSession.manualCaptureError,
    listening: transport === 'realtime' && realtimeSession.projection.listening,
    speaking: transport === 'realtime' && realtimeSession.projection.speaking,
    jobs: presentRealtimeJobs(realtimeSession, artifactAllowedOrigins),
    artifactAllowedOrigins,
    onToggleMute: transport === 'realtime' && !manualCaptureActive
      ? () => realtimeSession.setMuted(!realtimeSession.muted)
      : undefined,
    onToggleManualTurnTaking: transport === 'realtime' && realtimeSession.manualControlsAvailable && !manualCaptureActive
      ? () => {
        runOwnedRealtimeOperation(() => realtimeSession.setManualTurnTaking(!realtimeSession.manualTurnTaking));
      }
      : undefined,
    onStartManualTurn: transport === 'realtime'
      && realtimeSession.manualControlsAvailable
      && realtimeSession.manualTurnTaking
      && (realtimeSession.manualCaptureState === 'idle'
        || (realtimeSession.manualCaptureState === 'error' && realtimeSession.manualCaptureRetryable))
      ? realtimeSession.startManualTurn
      : undefined,
    onSendManualTurn: transport === 'realtime'
      && realtimeSession.manualControlsAvailable
      && realtimeSession.manualTurnTaking
      && realtimeSession.manualCaptureState === 'capturing'
      ? sendManualTurn
      : undefined,
    onDiscardManualTurn: transport === 'realtime'
      && realtimeSession.manualControlsAvailable
      && realtimeSession.manualTurnTaking
      && realtimeSession.manualCaptureState === 'capturing'
      ? discardManualTurn
      : undefined,
    onInterrupt: transport === 'realtime' ? cancelSpeech : undefined,
    onEndCall: transport === 'realtime' ? endRealtimeCall : undefined,
    onReconnect: transport === 'realtime' ? () => { void realtimeSession.connect().catch(dispatchError); } : undefined,
    onUseLegacy: transport === 'realtime' ? () => setTransport('legacy') : undefined,
    onRequestStatus: transport === 'realtime' ? (jobId) => {
      void realtimeSession.sendInput(`Give me a concise status update for delegated task ${jobId}.`)
        .catch((error: unknown) => dispatch({ type: 'error', message: (error as Error).message }));
    } : undefined,
    onRefine: transport === 'realtime' ? (jobId) => {
      const instruction = window.prompt('How should Hermes refine this task?')?.trim();
      if (instruction) runWorkerCommand(jobId, 'refine', workerControlPayload('refine', instruction));
    } : undefined,
    onRedirect: transport === 'realtime' ? (jobId) => {
      const instruction = window.prompt('What direction should Hermes take instead?')?.trim();
      if (instruction) runWorkerCommand(jobId, 'redirect', workerControlPayload('redirect', instruction));
    } : undefined,
    onCancel: transport === 'realtime' ? (jobId) => runWorkerCommand(jobId, 'cancel') : undefined,
  }), [cancelSpeech, discardManualTurn, dispatchError, endRealtimeCall, manualCaptureActive, realtimeSession, runOwnedRealtimeOperation, sendManualTurn, setTransport, transport]);

  return useMemo(() => ({
    acceptanceUnknown,
    acknowledgeAcceptanceUnknown,
    approval: transport === 'realtime' ? realtimeApproval : approval,
    bootstrap,
    cancelSpeech,
    closeClient,
    connect,
    connected,
    discardRecording,
    inputLevel,
    isCaptureSupported: browserSupportsCapture(),
    loadError,
    messages: projectedMessages,
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
    transport,
    setTransport,
    realtime,
  }), [
    acceptanceUnknown,
    acknowledgeAcceptanceUnknown,
    approval,
    realtimeApproval,
    bootstrap,
    cancelSpeech,
    closeClient,
    connect,
    connected,
    discardRecording,
    inputLevel,
    loadError,
    projectedMessages,
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
    transport,
    setTransport,
    realtime,
  ]);
}
