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
  connect: () => Promise<void>;
  close: () => void;
  setMuted: (muted: boolean) => void;
  setManualTurnTaking: (manual: boolean) => void;
  startManualTurn: () => void;
  stopManualTurn: () => void;
  sendInput: (text: string) => Promise<void>;
  interruptSpeech: () => Promise<void>;
  resolveApproval: (approvalId: string, choice: string) => Promise<void>;
  workerCommand: (workerJobId: string, operation: 'refine' | 'redirect' | 'cancel', revision: number, payload?: Record<string, unknown>) => Promise<void>;
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
  const identity = `${target}|${conversationId}`;
  const projectionIdentityRef = useRef(identity);

  const teardown = useCallback(() => {
    connectRef.current = null;
    controlRef.current?.close();
    controlRef.current = null;
    const client = mediaRef.current;
    mediaRef.current = null;
    const session = client?.close();
    if (session && target) {
      void closeRealtimeSession({
        target,
        sessionId: session.realtime_session_id,
        clientRequestId: realtimeRequestId('close'),
      }, getToken).catch(() => undefined);
    }
  }, [getToken, target]);

  useEffect(() => {
    let current = true;
    setCompatibility(null);
    setStateDetail(undefined);
    if (!enabled || !target) return () => { current = false; };
    void loadRealtimeCompatibility(target, getToken)
      .then((result) => {
        if (!current) return;
        setCompatibility(result);
        setStateDetail(result.compatible ? undefined : result.reasons.join('; '));
      })
      .catch((error: unknown) => {
        if (!current) return;
        setCompatibility({ compatible: false, version: null, reasons: [(error as Error).message], contract: {} });
        setStateDetail((error as Error).message);
      });
    return () => { current = false; };
  }, [enabled, getToken, target]);

  const connect = useCallback(async () => {
    if (!enabled) throw new Error('Realtime mode is disabled');
    if (!target || !conversationId) throw new Error('Select a target and conversation first');
    if (!compatibility?.compatible) throw new Error(stateDetail ?? 'Realtime compatibility preflight has not passed');
    setSuspended(false);
    const signature = `${target}|${conversationId}|${turnMode}`;
    if (signatureRef.current === signature && mediaRef.current?.isConnected && controlRef.current?.isReady) return;
    if (connectRef.current && signatureRef.current === signature) return connectRef.current;
    teardown();
    signatureRef.current = signature;
    const media = new RealtimeClient({
      onState: setMediaState,
      exchangeSdp: (sdpOffer) => createRealtimeSession({
        target,
        conversationId,
        sdpOffer,
        clientRequestId: realtimeRequestId('create'),
        turnMode,
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
      if (turnMode === 'manual' || mutedRef.current) media.setMuted(true);
    }).catch((error: unknown) => {
      setStateDetail((error as Error).message);
      throw error;
    }).finally(() => {
      if (connectRef.current === promise) connectRef.current = null;
    });
    connectRef.current = promise;
    return promise;
  }, [compatibility?.compatible, conversationId, enabled, getToken, stateDetail, target, teardown, turnMode]);

  useEffect(() => {
    if (!enabled || suspended || !compatibility?.compatible || !conversationId) return undefined;
    void connect().catch(() => undefined);
    return undefined;
  }, [compatibility?.compatible, connect, conversationId, enabled, suspended]);

  useEffect(() => teardown, [teardown, target, conversationId]);
  useEffect(() => {
    setSuspended(false);
    cursorRef.current = null;
    projectionIdentityRef.current = identity;
    dispatchProjection({ type: 'reset' });
  }, [identity]);

  const close = useCallback(() => {
    setSuspended(true);
    teardown();
  }, [teardown]);

  const setMuted = useCallback((value: boolean) => {
    mutedRef.current = value;
    setMutedState(value);
    mediaRef.current?.setMuted(value || turnMode === 'manual');
  }, [turnMode]);
  const setManualTurnTaking = useCallback((manual: boolean) => {
    if ((manual ? 'manual' : 'server_vad') === turnMode) return;
    setTurnMode(manual ? 'manual' : 'server_vad');
    teardown();
  }, [teardown, turnMode]);
  const startManualTurn = useCallback(() => {
    if (turnMode === 'manual' && !muted) mediaRef.current?.setMuted(false);
  }, [muted, turnMode]);
  const stopManualTurn = useCallback(() => {
    if (turnMode === 'manual') mediaRef.current?.setMuted(true);
  }, [turnMode]);
  const requireControl = useCallback(() => {
    const control = controlRef.current;
    const session = mediaRef.current?.activeSession;
    if (!control?.isReady || !session) throw new Error('Hermes Realtime control is not ready');
    return { control, session };
  }, []);
  const sendInput = useCallback(async (text: string) => {
    const { control, session } = requireControl();
    await control.input(realtimeRequestId('input'), text, session.session_generation);
  }, [requireControl]);
  const interruptSpeech = useCallback(async () => {
    const { control, session } = requireControl();
    await control.interrupt(realtimeRequestId('interrupt'), session.session_generation);
  }, [requireControl]);
  const resolveApproval = useCallback(async (approvalId: string, choice: string) => {
    const { control, session } = requireControl();
    await control.approval(realtimeRequestId('approval'), approvalId, choice, session.session_generation);
  }, [requireControl]);
  const workerCommand = useCallback(async (workerJobId: string, operation: 'refine' | 'redirect' | 'cancel', revision: number, payload: Record<string, unknown> = {}) => {
    const { control } = requireControl();
    const result = await control.workerCommand(realtimeRequestId('worker'), workerJobId, operation, revision, payload);
    dispatchProjection({ type: 'worker.revision', jobId: workerJobId, revision: result.resulting_revision });
  }, [requireControl]);

  const state = useMemo<RealtimeSessionState>(() => {
    if (!enabled) return 'disabled';
    if (suspended) return 'disconnected';
    if (!compatibility) return 'checking';
    if (!compatibility.compatible) return 'blocked';
    if (controlState === 'reconnecting') return 'reconnecting';
    if (controlState === 'degraded') return 'degraded';
    if (mediaState === 'failed') return 'failed';
    if (mediaState !== 'connected') return 'connecting_audio';
    if (controlState !== 'ready') return 'attaching_hermes';
    return 'ready';
  }, [compatibility, controlState, enabled, mediaState, suspended]);

  return useMemo(() => ({
    state,
    stateDetail,
    compatibility,
    mediaState,
    controlState,
    projection: projectionForIdentity(projection, projectionIdentityRef.current, identity),
    connected: state === 'ready',
    muted,
    manualTurnTaking: turnMode === 'manual',
    connect,
    close,
    setMuted,
    setManualTurnTaking,
    startManualTurn,
    stopManualTurn,
    sendInput,
    interruptSpeech,
    resolveApproval,
    workerCommand,
  }), [close, compatibility, connect, controlState, identity, mediaState, muted, projection, resolveApproval, sendInput, setManualTurnTaking, setMuted, startManualTurn, state, stateDetail, stopManualTurn, turnMode, workerCommand, interruptSpeech]);
}
