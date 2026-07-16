import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import {
  activateRealtimeSession,
  closeRealtimeSession,
  createRealtimeSession,
  loadRealtimeCompatibility,
  type AuthTokenProvider,
} from '../lib/api';
import { RealtimeClient } from '../lib/realtimeClient';
import { RealtimeControlClient } from '../lib/realtimeControlClient';
import {
  realtimeRequestId,
  type RealtimeCompatibility,
  type RealtimeControlState,
  type RealtimeMediaState,
  type RealtimeTurnMode,
} from '../lib/realtimeTypes';
import {
  emptyRealtimeProjection,
  projectRealtimeEvent,
  projectRealtimeSnapshot,
  type RealtimeConversationProjection,
} from './conversationProjection';

export type RealtimeSessionState =
  | 'disabled'
  | 'checking'
  | 'blocked'
  | 'connecting_audio'
  | 'attaching_hermes'
  | 'ready'
  | 'reconnecting'
  | 'degraded'
  | 'disconnected'
  | 'failed';

export interface RealtimeSessionController {
  state: RealtimeSessionState;
  stateDetail?: string;
  compatibility: RealtimeCompatibility | null;
  mediaState: RealtimeMediaState;
  controlState: RealtimeControlState;
  projection: RealtimeConversationProjection;
  connected: boolean;
  muted: boolean;
  manualTurnTaking: boolean;
  manualControlsAvailable: boolean;
  manualCaptureState: 'idle' | 'starting' | 'capturing' | 'committing' | 'discarding' | 'error';
  manualCaptureError?: string;
  manualCaptureRetryable: boolean;
  connect: () => Promise<void>;
  close: () => void;
  setMuted: (muted: boolean) => void;
  setManualTurnTaking: (manual: boolean) => Promise<void>;
  startManualTurn: () => void;
  stopManualTurn: () => void;
  discardManualTurn: () => Promise<void>;
  commitManualTurn: () => Promise<void>;
  sendInput: (text: string) => Promise<void>;
  interruptSpeech: () => Promise<void>;
  resolveApproval: (approvalId: string, choice: string) => Promise<void>;
  submittingApprovalId: string | null;
  workerCommand: (workerJobId: string, operation: 'refine' | 'redirect' | 'cancel', revision: number, payload?: Record<string, unknown>) => Promise<void>;
}

export function supportsManualTurnControls(compatibility: RealtimeCompatibility | null): boolean {
  // `compatible` is the backend proof that the required commit/turn-mode endpoint keys exist.
  // The retained contract then proves the matching session capabilities and modes.
  if (!compatibility?.compatible) return false;
  const sessions = compatibility.contract.sessions;
  if (!sessions || typeof sessions !== 'object' || Array.isArray(sessions)) return false;
  const contract = sessions as Record<string, unknown>;
  return contract.manual_audio_commit === true
    && contract.manual_audio_discard === true
    && contract.turn_mode_update === true
    && Array.isArray(contract.turn_modes)
    && contract.turn_modes.includes('server_vad')
    && contract.turn_modes.includes('manual');
}

function resultRetryableError(message: string): boolean {
  return message.startsWith('No audio was captured.');
}

export function projectionForIdentity(
  projection: RealtimeConversationProjection,
  projectionIdentity: string,
  currentIdentity: string,
): RealtimeConversationProjection {
  return projectionIdentity === currentIdentity ? projection : emptyRealtimeProjection;
}

export function useRealtimeSession({
  enabled,
  target,
  conversationId,
  getToken,
}: {
  enabled: boolean;
  target: string;
  conversationId: string;
  getToken: AuthTokenProvider;
}): RealtimeSessionController {
  const [compatibility, setCompatibility] = useState<RealtimeCompatibility | null>(null);
  const [stateDetail, setStateDetail] = useState<string>();
  const [mediaState, setMediaState] = useState<RealtimeMediaState>('idle');
  const [controlState, setControlState] = useState<RealtimeControlState>('idle');
  const [muted, setMutedState] = useState(false);
  const [suspended, setSuspended] = useState(false);
  const [turnMode, setTurnMode] = useState<RealtimeTurnMode>('server_vad');
  const [manualCaptureState, setManualCaptureState] = useState<'idle' | 'starting' | 'capturing' | 'committing' | 'discarding' | 'error'>('idle');
  const [manualCaptureError, setManualCaptureError] = useState<string>();
  const [manualCaptureRetryable, setManualCaptureRetryable] = useState(true);
  const [compatibilityTarget, setCompatibilityTarget] = useState('');
  const [submittingApprovalId, setSubmittingApprovalId] = useState<string | null>(null);
  const [projection, dispatchProjection] = useReducer(
    (current: RealtimeConversationProjection, action: { type: 'reset' } | { type: 'snapshot'; value: Parameters<typeof projectRealtimeSnapshot>[0] } | { type: 'event'; value: Parameters<typeof projectRealtimeEvent>[1] } | { type: 'worker.revision'; jobId: string; revision: number }) => {
      if (action.type === 'reset') return emptyRealtimeProjection;
      if (action.type === 'worker.revision') return {
        ...current,
        workerJobs: {
          ...current.workerJobs,
          [action.jobId]: { ...current.workerJobs[action.jobId], revision: action.revision },
        },
      };
      return action.type === 'snapshot' ? projectRealtimeSnapshot(action.value) : projectRealtimeEvent(current, action.value);
    },
    emptyRealtimeProjection,
  );
  const mediaRef = useRef<RealtimeClient | null>(null);
  const controlRef = useRef<RealtimeControlClient | null>(null);
  const connectRef = useRef<Promise<void> | null>(null);
  const signatureRef = useRef('');
  const cursorRef = useRef<string | null>(null);
  const mutedRef = useRef(false);
  const turnModeRef = useRef<RealtimeTurnMode>('server_vad');
  const identity = `${target}|${conversationId}`;
  const projectionIdentityRef = useRef(identity);
  const modeIdentityRef = useRef(identity);
  const operationEpochRef = useRef(0);
  const modeRequestRef = useRef<{
    epoch: number;
    identity: string;
    sessionId: string;
    generation: number;
    manual: boolean;
    promise: Promise<void>;
  } | null>(null);
  const manualTurnRef = useRef<{
    epoch: number;
    identity: string;
    sessionId: string;
    generation: number;
    clientRequestId: string;
    state: 'capturing' | 'committing' | 'discarding' | 'complete' | 'failed';
    discardRequestId?: string;
    promise?: Promise<void>;
  } | null>(null);
  const manualCaptureIdentityRef = useRef(identity);
  const approvalRequestRef = useRef<{
    approvalId: string;
    clientRequestId: string;
    promise: Promise<void>;
  } | null>(null);

  // Refs must cross the identity boundary before effects can run so a new call can
  // never inherit the previous conversation's manual mode or pending operation.
  if (modeIdentityRef.current !== identity) {
    operationEpochRef.current += 1;
    modeIdentityRef.current = identity;
    turnModeRef.current = 'server_vad';
    modeRequestRef.current = null;
    manualTurnRef.current = null;
    manualCaptureIdentityRef.current = identity;
  }

  const currentCompatibility = compatibilityTarget === target ? compatibility : null;

  const teardown = useCallback(() => {
    operationEpochRef.current += 1;
    modeRequestRef.current = null;
    manualTurnRef.current = null;
    manualCaptureIdentityRef.current = identity;
    setManualCaptureState('idle');
    setManualCaptureError(undefined);
    setManualCaptureRetryable(true);
    connectRef.current = null;
    controlRef.current?.close();
    controlRef.current = null;
    const client = mediaRef.current;
    client?.setMuted(true);
    mediaRef.current = null;
    const session = client?.close();
    if (session && target) {
      void closeRealtimeSession({
        target,
        sessionId: session.realtime_session_id,
        clientRequestId: realtimeRequestId('close'),
      }, getToken).catch(() => undefined);
    }
  }, [getToken, identity, target]);

  useEffect(() => {
    let current = true;
    setCompatibility(null);
    setCompatibilityTarget('');
    setStateDetail(undefined);
    if (!enabled || !target) return () => { current = false; };
    void loadRealtimeCompatibility(target, getToken)
      .then((result) => {
        if (!current) return;
        setCompatibility(result);
        setCompatibilityTarget(target);
        setStateDetail(result.compatible ? undefined : result.reasons.join('; '));
      })
      .catch((error: unknown) => {
        if (!current) return;
        setCompatibility({ compatible: false, version: null, reasons: [(error as Error).message], contract: {} });
        setCompatibilityTarget(target);
        setStateDetail((error as Error).message);
      });
    return () => { current = false; };
  }, [enabled, getToken, target]);

  const connect = useCallback(async () => {
    if (!enabled) throw new Error('Realtime mode is disabled');
    if (!target || !conversationId) throw new Error('Select a target and conversation first');
    if (!currentCompatibility?.compatible) throw new Error(stateDetail ?? 'Realtime compatibility preflight has not passed for this target');
    setSuspended(false);
    const signature = identity;
    if (signatureRef.current === signature && mediaRef.current?.isConnected && controlRef.current?.isReady) return;
    if (connectRef.current && signatureRef.current === signature) return connectRef.current;
    teardown();
    signatureRef.current = signature;
    const initialTurnMode = turnModeRef.current;
    const media = new RealtimeClient({
      onState: setMediaState,
      exchangeSdp: (sdpOffer) => createRealtimeSession({
        target,
        conversationId,
        sdpOffer,
        clientRequestId: realtimeRequestId('create'),
        turnMode: initialTurnMode,
      }, getToken),
      activate: (session) => activateRealtimeSession({
        target,
        sessionId: session.realtime_session_id,
        sessionGeneration: session.session_generation,
        clientRequestId: realtimeRequestId('activate'),
      }, getToken),
      releaseSession: (session) => closeRealtimeSession({
        target,
        sessionId: session.realtime_session_id,
        clientRequestId: realtimeRequestId('close'),
      }, getToken),
      // Feasibility proved the browser data channel is unnecessary. If introduced later,
      // RealtimeClient treats it as presentation-only and never as control authority.
      createUntrustedDataChannel: false,
    });
    mediaRef.current = media;
    const promise = media.connect().then(async (session) => {
      if (mediaRef.current !== media) throw new Error('Realtime connection was superseded');
      const control = new RealtimeControlClient({
        getToken,
        target,
        conversationId,
        sessionId: session.realtime_session_id,
        after: cursorRef.current,
        onSnapshot: (snapshot) => {
          cursorRef.current = snapshot.last_event_id;
          dispatchProjection({ type: 'snapshot', value: snapshot });
        },
        onEvent: (event) => {
          cursorRef.current = event.event_id;
          dispatchProjection({ type: 'event', value: event });
        },
        onState: (next) => {
          setControlState(next);
          if (next === 'ready') setStateDetail(undefined);
        },
        onError: setStateDetail,
      });
      controlRef.current = control;
      await control.connect();
      if (turnModeRef.current === 'manual' || mutedRef.current) media.setMuted(true);
    }).catch((error: unknown) => {
      setStateDetail((error as Error).message);
      throw error;
    }).finally(() => {
      if (connectRef.current === promise) connectRef.current = null;
    });
    connectRef.current = promise;
    return promise;
  }, [conversationId, currentCompatibility?.compatible, enabled, getToken, identity, stateDetail, target, teardown]);

  useEffect(() => {
    if (!enabled || suspended || !currentCompatibility?.compatible || !conversationId) return undefined;
    void connect().catch(() => undefined);
    return undefined;
  }, [connect, conversationId, currentCompatibility?.compatible, enabled, suspended]);

  useEffect(() => teardown, [teardown, target, conversationId]);
  useEffect(() => {
    setSuspended(false);
    cursorRef.current = null;
    projectionIdentityRef.current = identity;
    modeIdentityRef.current = identity;
    turnModeRef.current = 'server_vad';
    setTurnMode('server_vad');
    manualCaptureIdentityRef.current = identity;
    setManualCaptureState('idle');
    setManualCaptureError(undefined);
    setManualCaptureRetryable(true);
    dispatchProjection({ type: 'reset' });
  }, [identity]);

  useEffect(() => {
    if (!submittingApprovalId) return;
    const approval = projection.approvals[submittingApprovalId];
    if (!approval || !['pending', 'resolving'].includes(String(approval.state))) {
      approvalRequestRef.current = null;
      setSubmittingApprovalId(null);
    }
  }, [projection.approvals, submittingApprovalId]);

  const close = useCallback(() => {
    setSuspended(true);
    teardown();
  }, [teardown]);

  const setMuted = useCallback((value: boolean) => {
    mutedRef.current = value;
    setMutedState(value);
    mediaRef.current?.setMuted(value || turnModeRef.current === 'manual');
  }, []);
  const requireControl = useCallback(() => {
    const control = controlRef.current;
    const session = mediaRef.current?.activeSession;
    if (
      !control?.isReady
      || !session
      || signatureRef.current !== identity
      || session.conversation_id !== conversationId
    ) throw new Error('Hermes Realtime control is not ready for this conversation');
    return { control, session };
  }, [conversationId, identity]);
  const setManualTurnTaking = useCallback((manual: boolean): Promise<void> => {
    if (!supportsManualTurnControls(currentCompatibility)) {
      return Promise.reject(new Error('This Hermes target does not support server-authoritative manual turns'));
    }
    let required: ReturnType<typeof requireControl>;
    try { required = requireControl(); }
    catch (error) { return Promise.reject(error); }
    const { control, session } = required;
    const effectiveManual = modeIdentityRef.current === identity && turnModeRef.current === 'manual';
    if (manual === effectiveManual) return Promise.resolve();
    if (manualTurnRef.current && ['capturing', 'committing', 'discarding'].includes(manualTurnRef.current.state)) {
      return Promise.reject(new Error('Finish or discard the current manual recording before changing turn mode'));
    }
    const epoch = operationEpochRef.current;
    const existing = modeRequestRef.current;
    if (existing) {
      if (
        existing.epoch === epoch
        && existing.identity === identity
        && existing.sessionId === session.realtime_session_id
        && existing.generation === session.session_generation
        && existing.manual === manual
      ) return existing.promise;
      return Promise.reject(new Error('Another Hermes turn mode change is already pending'));
    }
    const clientRequestId = realtimeRequestId('turn-mode');
    if (manual) mediaRef.current?.setMuted(true);
    const promise = control.turnModeUpdate(
      clientRequestId,
      session.session_generation,
      manual ? 'manual' : 'automatic',
    ).then((result) => {
      if (result.state === 'outcome_unknown' || result.state === 'in_progress') {
        throw new Error('Hermes could not confirm the turn mode change. The current mode was kept and the request will not be retried automatically.');
      }
      if (
        operationEpochRef.current !== epoch
        || signatureRef.current !== identity
        || mediaRef.current?.activeSession?.realtime_session_id !== session.realtime_session_id
        || mediaRef.current.activeSession.session_generation !== session.session_generation
      ) throw new Error('The turn mode change belonged to a previous Realtime session');
      turnModeRef.current = manual ? 'manual' : 'server_vad';
      modeIdentityRef.current = identity;
      setTurnMode(turnModeRef.current);
      manualTurnRef.current = null;
      manualCaptureIdentityRef.current = identity;
      setManualCaptureState('idle');
      setManualCaptureError(undefined);
      setManualCaptureRetryable(true);
      mediaRef.current?.setMuted(manual || mutedRef.current);
    }).catch((error: unknown) => {
      if (operationEpochRef.current === epoch) {
        // A failed or ambiguous mode mutation can have crossed the server boundary.
        // Fail locally muted until the user explicitly recovers or changes mode again.
        mutedRef.current = true;
        setMutedState(true);
        mediaRef.current?.setMuted(true);
        setStateDetail((error as Error).message);
      }
      throw error;
    }).finally(() => {
      if (modeRequestRef.current?.promise === promise) modeRequestRef.current = null;
    });
    modeRequestRef.current = {
      epoch,
      identity,
      sessionId: session.realtime_session_id,
      generation: session.session_generation,
      manual,
      promise,
    };
    return promise;
  }, [currentCompatibility, identity, requireControl]);
  const startManualTurn = useCallback(() => {
    if (manualCaptureState === 'error' && !manualCaptureRetryable) return;
    let required: ReturnType<typeof requireControl>;
    try { required = requireControl(); }
    catch { return; }
    const { control, session } = required;
    if (
      turnModeRef.current !== 'manual'
      || !supportsManualTurnControls(currentCompatibility)
    ) return;
    const epoch = operationEpochRef.current;
    const existing = manualTurnRef.current;
    if (
      existing
      && existing.epoch === epoch
      && existing.identity === identity
      && existing.sessionId === session.realtime_session_id
      && existing.generation === session.session_generation
      && ['capturing', 'committing', 'discarding'].includes(existing.state)
    ) return;
    manualTurnRef.current = {
      epoch,
      identity,
      sessionId: session.realtime_session_id,
      generation: session.session_generation,
      clientRequestId: realtimeRequestId('manual-commit'),
      state: 'capturing',
    };
    manualCaptureIdentityRef.current = identity;
    setManualCaptureState('capturing');
    setManualCaptureError(undefined);
    setManualCaptureRetryable(false);
    mutedRef.current = false;
    setMutedState(false);
    if (control.isReady) mediaRef.current?.setMuted(false);
  }, [currentCompatibility, identity, manualCaptureRetryable, manualCaptureState, requireControl]);
  const stopManualTurn = useCallback(() => {
    if (turnModeRef.current === 'manual') mediaRef.current?.setMuted(true);
  }, []);
  const discardManualTurn = useCallback((): Promise<void> => {
    let required: ReturnType<typeof requireControl>;
    try { required = requireControl(); }
    catch (error) { return Promise.reject(error); }
    const { control, session } = required;
    const operation = manualTurnRef.current;
    const epoch = operationEpochRef.current;
    if (
      turnModeRef.current !== 'manual'
      || !operation
      || operation.epoch !== epoch
      || operation.identity !== identity
      || operation.sessionId !== session.realtime_session_id
      || operation.generation !== session.session_generation
    ) return Promise.reject(new Error('There is no manual recording to discard'));
    if (operation.promise) return operation.promise;
    mediaRef.current?.setMuted(true);
    operation.state = 'discarding';
    operation.discardRequestId ??= realtimeRequestId('manual-discard');
    manualCaptureIdentityRef.current = identity;
    setManualCaptureState('discarding');
    setManualCaptureError(undefined);
    setManualCaptureRetryable(false);
    const promise = control.manualAudioDiscard(operation.discardRequestId, session.session_generation)
      .then((result) => {
        if (result.state === 'rejected') {
          operation.state = 'failed';
          throw new Error('Hermes could not discard the manual recording. Reconnect before recording again.');
        }
        if (result.state === 'outcome_unknown' || result.state === 'in_progress') {
          operation.state = 'complete';
          throw new Error('Hermes could not confirm whether the manual recording was discarded. It will not be retried automatically; reconnect before recording again.');
        }
        if (
          operationEpochRef.current !== epoch
          || signatureRef.current !== identity
          || mediaRef.current?.activeSession?.realtime_session_id !== session.realtime_session_id
          || mediaRef.current.activeSession.session_generation !== session.session_generation
        ) throw new Error('The manual discard belonged to a previous Realtime session');
        operation.state = 'complete';
        if (manualTurnRef.current === operation) manualTurnRef.current = null;
        setManualCaptureState('idle');
        setManualCaptureError(undefined);
        setManualCaptureRetryable(true);
      })
      .catch((error: unknown) => {
        if (operationEpochRef.current === epoch) {
          const message = (error as Error).message;
          setManualCaptureState('error');
          setManualCaptureError(message);
          setManualCaptureRetryable(false);
          setStateDetail(message);
        }
        throw error;
      });
    operation.promise = promise;
    return promise;
  }, [identity, requireControl]);
  const commitManualTurn = useCallback((): Promise<void> => {
    let required: ReturnType<typeof requireControl>;
    try { required = requireControl(); }
    catch (error) { return Promise.reject(error); }
    const { control, session } = required;
    const operation = manualTurnRef.current;
    const epoch = operationEpochRef.current;
    if (
      turnModeRef.current !== 'manual'
      || !operation
      || operation.epoch !== epoch
      || operation.identity !== identity
      || operation.sessionId !== session.realtime_session_id
      || operation.generation !== session.session_generation
    ) return Promise.reject(new Error('Start recording before sending a manual turn'));
    if (operation.promise) return operation.promise;
    mediaRef.current?.setMuted(true);
    operation.state = 'committing';
    manualCaptureIdentityRef.current = identity;
    setManualCaptureState('committing');
    setManualCaptureError(undefined);
    setManualCaptureRetryable(false);
    const promise = control.manualAudioCommit(operation.clientRequestId, session.session_generation)
      .then((result) => {
        if (result.state === 'rejected') {
          operation.state = 'failed';
          throw new Error('No audio was captured. Start recording, speak, and send the turn again.');
        }
        if (result.state === 'outcome_unknown' || result.state === 'in_progress') {
          operation.state = 'complete';
          throw new Error('Hermes could not confirm whether the manual turn was accepted. It will not be retried automatically.');
        }
        if (
          operationEpochRef.current !== epoch
          || signatureRef.current !== identity
          || mediaRef.current?.activeSession?.realtime_session_id !== session.realtime_session_id
          || mediaRef.current.activeSession.session_generation !== session.session_generation
        ) throw new Error('The manual turn belonged to a previous Realtime session');
        operation.state = 'complete';
        setManualCaptureState('idle');
        setManualCaptureError(undefined);
        setManualCaptureRetryable(true);
      })
      .catch((error: unknown) => {
        if (operationEpochRef.current === epoch && operation.state === 'committing') operation.state = 'failed';
        if (operationEpochRef.current === epoch) {
          const message = (error as Error).message;
          setManualCaptureState('error');
          setManualCaptureError(message);
          setManualCaptureRetryable(resultRetryableError(message));
          setStateDetail(message);
        }
        throw error;
      });
    operation.promise = promise;
    return promise;
  }, [identity, requireControl]);
  const sendInput = useCallback(async (text: string) => {
    const { control, session } = requireControl();
    await control.input(realtimeRequestId('input'), text, session.session_generation);
  }, [requireControl]);
  const interruptSpeech = useCallback(async () => {
    const { control, session } = requireControl();
    await control.interrupt(realtimeRequestId('interrupt'), session.session_generation);
  }, [requireControl]);
  const resolveApproval = useCallback((approvalId: string, choice: string): Promise<void> => {
    const { control, session } = requireControl();
    const existing = approvalRequestRef.current;
    if (existing) {
      if (existing.approvalId === approvalId) return existing.promise;
      return Promise.reject(new Error('Another Hermes approval is already being submitted'));
    }
    const clientRequestId = realtimeRequestId('approval');
    setSubmittingApprovalId(approvalId);
    const promise = control.approval(clientRequestId, approvalId, choice, session.session_generation)
      .then(() => undefined)
      .catch((error: unknown) => {
        if (approvalRequestRef.current?.clientRequestId === clientRequestId) {
          approvalRequestRef.current = null;
          setSubmittingApprovalId(null);
        }
        throw error;
      });
    approvalRequestRef.current = { approvalId, clientRequestId, promise };
    return promise;
  }, [requireControl]);
  const workerCommand = useCallback(async (workerJobId: string, operation: 'refine' | 'redirect' | 'cancel', revision: number, payload: Record<string, unknown> = {}) => {
    const { control } = requireControl();
    const result = await control.workerCommand(realtimeRequestId('worker'), workerJobId, operation, revision, payload);
    dispatchProjection({ type: 'worker.revision', jobId: workerJobId, revision: result.revision });
    if (result.acknowledgement.startsWith('rejected_')) {
      throw new Error(`Hermes rejected ${operation}: ${result.acknowledgement.replaceAll('_', ' ')} (revision ${result.revision})`);
    }
  }, [requireControl]);

  const state = useMemo<RealtimeSessionState>(() => {
    if (!enabled) return 'disabled';
    if (suspended) return 'disconnected';
    if (!currentCompatibility) return 'checking';
    if (!currentCompatibility.compatible) return 'blocked';
    if (controlState === 'reconnecting') return 'reconnecting';
    if (controlState === 'degraded') return 'degraded';
    if (mediaState === 'failed') return 'failed';
    if (mediaState !== 'connected') return 'connecting_audio';
    if (controlState !== 'ready') return 'attaching_hermes';
    return 'ready';
  }, [controlState, currentCompatibility, enabled, mediaState, suspended]);

  return useMemo(() => ({
    state,
    stateDetail,
    compatibility: currentCompatibility,
    mediaState,
    controlState,
    projection: projectionForIdentity(projection, projectionIdentityRef.current, identity),
    connected: state === 'ready',
    muted,
    manualTurnTaking: modeIdentityRef.current === identity && turnModeRef.current === 'manual',
    manualControlsAvailable: state === 'ready' && supportsManualTurnControls(currentCompatibility),
    manualCaptureState: manualCaptureIdentityRef.current === identity ? manualCaptureState : 'idle',
    manualCaptureError: manualCaptureIdentityRef.current === identity ? manualCaptureError : undefined,
    manualCaptureRetryable: manualCaptureIdentityRef.current === identity && manualCaptureRetryable,
    connect,
    close,
    setMuted,
    setManualTurnTaking,
    startManualTurn,
    stopManualTurn,
    discardManualTurn,
    commitManualTurn,
    sendInput,
    interruptSpeech,
    resolveApproval,
    submittingApprovalId,
    workerCommand,
  }), [close, commitManualTurn, connect, controlState, currentCompatibility, discardManualTurn, identity, manualCaptureError, manualCaptureRetryable, manualCaptureState, mediaState, muted, projection, resolveApproval, sendInput, setManualTurnTaking, setMuted, startManualTurn, state, stateDetail, stopManualTurn, submittingApprovalId, turnMode, workerCommand, interruptSpeech]);
}
