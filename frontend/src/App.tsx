import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { ApprovalModal, type PendingApproval } from './components/ApprovalModal';
import { DiagnosticsPanel } from './components/DiagnosticsPanel';
import { RunTimeline } from './components/RunTimeline';
import { SessionPicker } from './components/SessionPicker';
import { TargetPicker } from './components/TargetPicker';
import { TranscriptPanel } from './components/TranscriptPanel';
import { VoiceControls } from './components/VoiceControls';
import { getStoredToken, loadBootstrap, setStoredToken } from './lib/api';
import { browserSupportsCapture, startPcm16Capture, type CaptureSession } from './lib/capture';
import { PlaybackQueue } from './lib/playback';
import { consoleReducer, initialConsoleState, nextTurnId } from './lib/state';
import type { Bootstrap, TimelineItem, VoiceServerEvent } from './lib/types';
import { VoiceClient } from './lib/voiceClient';

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

function approvalChoices(payload: Record<string, unknown>): Array<'once' | 'session' | 'always' | 'deny'> {
  const raw = payload.choices;
  const allowed = new Set(['once', 'session', 'always', 'deny']);
  if (Array.isArray(raw)) {
    const choices = raw.filter((item): item is 'once' | 'session' | 'always' | 'deny' => typeof item === 'string' && allowed.has(item));
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

export function App() {
  const [token, setToken] = useState(getStoredToken());
  const [tokenDraft, setTokenDraft] = useState(getStoredToken());
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedTarget, setSelectedTarget] = useState('');
  const [sessionKey, setSessionKey] = useState('');
  const [speakReplies, setSpeakReplies] = useState(false);
  const [state, dispatch] = useReducer(consoleReducer, initialConsoleState);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [transcript, setTranscript] = useState('');
  const [response, setResponse] = useState('');
  const [approval, setApproval] = useState<PendingApproval | null>(null);
  const [connected, setConnected] = useState(false);
  const clientRef = useRef<VoiceClient | null>(null);
  const clientSignatureRef = useRef('');
  const captureRef = useRef<CaptureSession | null>(null);
  const playbackRef = useRef(new PlaybackQueue());
  const stopRequestedRef = useRef(false);
  const activeRunIdRef = useRef<string | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);

  const closeClient = useCallback(() => {
    clientRef.current?.close();
    clientRef.current = null;
    clientSignatureRef.current = '';
    setConnected(false);
  }, []);

  useEffect(() => {
    let active = true;
    if (!token) return;
    loadBootstrap(token)
      .then((data) => {
        if (!active) return;
        setBootstrap(data);
        setLoadError(null);
        const first = data.targets[0];
        setSelectedTarget((current) => current || first?.name || '');
        setSessionKey((current) => current || first?.default_session_key || 'voice-console');
        setSpeakReplies(data.voice.speak_replies_default);
      })
      .catch((err) => {
        if (!active) return;
        setLoadError((err as Error).message);
        setBootstrap(null);
      });
    return () => { active = false; };
  }, [token]);

  const selected = useMemo(() => bootstrap?.targets.find((target) => target.name === selectedTarget), [bootstrap, selectedTarget]);

  const appendEvent = useCallback((event: VoiceServerEvent) => {
    setTimeline((items) => [...items, { id: `${Date.now()}-${items.length}`, ts: Date.now(), kind: event.type, message: timelineMessage(event), payload: event }].slice(-100));
  }, []);

  const handleEvent = useCallback((event: VoiceServerEvent) => {
    if (hasRunId(event) && activeRunIdRef.current && event.type !== 'agent.run.started' && event.run_id !== activeRunIdRef.current) return;
    if (hasTurnId(event) && activeTurnIdRef.current && event.turn_id !== activeTurnIdRef.current) return;
    appendEvent(event);
    dispatch({ type: 'event', event });
    if (event.type === 'ready') setConnected(true);
    if (event.type === 'recording.started') activeTurnIdRef.current = event.turn_id;
    if (event.type === 'transcript.final') setTranscript(event.text);
    if (event.type === 'agent.run.started') {
      activeRunIdRef.current = event.run_id;
      setResponse('');
      setApproval(null);
    }
    if (event.type === 'agent.delta') setResponse((prev) => prev + event.delta);
    if (event.type === 'agent.completed') setResponse(event.text);
    if (event.type === 'agent.approval.request') {
      setApproval({
        runId: event.run_id,
        message: String(event.approval.message ?? 'Hermes needs approval to continue.'),
        choices: approvalChoices(event.approval),
        payload: event.approval,
      });
    }
    if (event.type === 'agent.approval.resolved' || event.type === 'agent.approval.responded') setApproval(null);
    if (event.type === 'agent.failed' || event.type === 'agent.stopped' || event.type === 'agent.completed') activeRunIdRef.current = null;
    if (event.type === 'tts.start') playbackRef.current.start(event.turn_id);
    if (event.type === 'tts.end') playbackRef.current.end(event.turn_id);
    if (event.type === 'tts.cancelled') playbackRef.current.cancel(event.turn_id);
    if (event.type === 'error') dispatch({ type: 'error', message: event.message });
  }, [appendEvent]);

  const ensureClient = useCallback(async () => {
    if (!selectedTarget || !sessionKey) throw new Error('Select a target and session first');
    const signature = `${selectedTarget}|${sessionKey}|${speakReplies}`;
    if (clientRef.current?.isOpen && clientSignatureRef.current === signature) return clientRef.current;
    closeClient();
    const client = new VoiceClient({
      token,
      onEvent: handleEvent,
      onAudio: (chunk) => playbackRef.current.pushChunk(chunk),
      onClose: () => setConnected(false),
      onError: (message) => dispatch({ type: 'error', message }),
    });
    await client.connect({ target: selectedTarget, sessionId: sessionKey, speakReplies });
    clientRef.current = client;
    clientSignatureRef.current = signature;
    return client;
  }, [closeClient, handleEvent, selectedTarget, sessionKey, speakReplies, token]);

  const startRecording = useCallback(async () => {
    const turnId = nextTurnId();
    stopRequestedRef.current = false;
    activeTurnIdRef.current = turnId;
    dispatch({ type: 'recording.start', turnId });
    try {
      const client = await ensureClient();
      await client.startRecording(turnId);
      if (stopRequestedRef.current) {
        client.stopRecording(turnId);
        dispatch({ type: 'recording.stop' });
        return;
      }
      const capture = await startPcm16Capture((chunk) => client.sendAudio(chunk));
      captureRef.current = capture;
      if (stopRequestedRef.current) {
        client.stopRecording(turnId);
        dispatch({ type: 'recording.stop' });
        await capture.stop();
        captureRef.current = null;
      }
    } catch (err) {
      dispatch({ type: 'error', message: (err as Error).message });
      await captureRef.current?.stop();
      captureRef.current = null;
    }
  }, [ensureClient]);

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

  const cancelSpeech = useCallback(() => {
    const turnId = playbackRef.current.activeTurnId ?? activeTurnIdRef.current ?? '';
    playbackRef.current.cancel(turnId);
    if (turnId) clientRef.current?.cancelTts(turnId);
    dispatch({ type: 'playback.cancel' });
  }, []);

  const handleSpeakReplies = useCallback((value: boolean) => {
    if (!value) cancelSpeech();
    if (value !== speakReplies) closeClient();
    setSpeakReplies(value);
  }, [cancelSpeech, closeClient, speakReplies]);

  const resolveApproval = useCallback((decision: 'once' | 'session' | 'always' | 'deny') => {
    if (!approval) return;
    setApproval({ ...approval, submitting: true });
    clientRef.current?.resolveApproval(approval.runId, decision);
  }, [approval]);

  const stopRun = useCallback(() => {
    if (state.activeRunId) clientRef.current?.stopRun(state.activeRunId);
  }, [state.activeRunId]);

  const saveToken = () => {
    setStoredToken(tokenDraft);
    setToken(tokenDraft);
  };

  if (!token || !bootstrap) {
    return (
      <main className="shell auth-shell">
        <section className="card auth-card">
          <h1>Hermes Voice Console</h1>
          <p>Enter the console token from <code>VOICE_CONSOLE_SESSION_SECRET</code>.</p>
          <input aria-label="Console token" type="password" value={tokenDraft} onChange={(event) => setTokenDraft(event.target.value)} />
          <button onClick={saveToken}>Unlock</button>
          {loadError ? <p className="error">{loadError}</p> : null}
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Standalone companion · no Hermes source patch</p>
          <h1>Hermes Voice Console</h1>
          <p>Browser mic → console STT → Hermes API Server → console TTS → browser playback.</p>
        </div>
        <button onClick={() => { closeClient(); setStoredToken(''); setToken(''); }}>Lock</button>
      </header>

      <section className="card grid two">
        <TargetPicker targets={bootstrap.targets} value={selectedTarget} onChange={(name) => {
          setSelectedTarget(name);
          const target = bootstrap.targets.find((item) => item.name === name);
          setSessionKey(target?.default_session_key ?? 'voice-console');
          closeClient();
        }} />
        <SessionPicker value={sessionKey} onChange={(value) => { setSessionKey(value); closeClient(); }} />
      </section>

      {selected && !selected.api_key_configured ? <p className="warning">Selected target is missing its server-side API key env var.</p> : null}

      <VoiceControls
        recording={state.recording}
        supported={browserSupportsCapture()}
        speakReplies={speakReplies}
        onSpeakReplies={handleSpeakReplies}
        onStart={startRecording}
        onStop={stopRecording}
        onCancelSpeech={cancelSpeech}
      />

      <div className="grid two">
        <TranscriptPanel transcript={transcript} response={response} />
        <DiagnosticsPanel bootstrap={bootstrap} recording={state.recording} agent={state.agent} playback={state.playback} error={state.error ?? loadError ?? undefined} connected={connected} />
      </div>

      <section className="card button-row">
        <button onClick={() => void ensureClient()}>Connect / probe target</button>
        <button onClick={stopRun} disabled={state.agent !== 'running' && state.agent !== 'waiting_for_approval'}>Stop current Hermes run</button>
      </section>

      <RunTimeline items={timeline} />
      <ApprovalModal approval={approval} onResolve={resolveApproval} />
    </main>
  );
}
