function verboseEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return new URLSearchParams(window.location.search).get('voiceDebug') === '1'
      || window.localStorage.getItem('hvc_debug') === '1';
  } catch {
    return false;
  }
}

export function voiceDiagnostic(
  event: string,
  fields: Record<string, unknown> = {},
  verboseOnly = false,
): void {
  if (verboseOnly && !verboseEnabled()) return;
  // Never pass tokens, prompts, transcript text, or agent output here.
  console.info('[hermes-voice-console]', { event, at: new Date().toISOString(), ...fields });
}
