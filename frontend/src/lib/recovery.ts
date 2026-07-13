const RECOVERY_KEY = 'hvc.recovery.v1';
const RECOVERY_TTL_MS = 2 * 60 * 60 * 1000;

export interface RecoveryMetadata {
  version: 1;
  target: string;
  conversationId: string;
  runId: string;
  lastSequence: number;
  savedAt: number;
  expiresAt: number;
}

export function loadRecovery(): RecoveryMetadata | null {
  const raw = window.sessionStorage.getItem(RECOVERY_KEY);
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<RecoveryMetadata>;
    if (
      value.version !== 1
      || typeof value.target !== 'string'
      || typeof value.conversationId !== 'string'
      || typeof value.runId !== 'string'
      || typeof value.lastSequence !== 'number'
      || typeof value.savedAt !== 'number'
      || typeof value.expiresAt !== 'number'
      || value.expiresAt <= Date.now()
    ) {
      clearRecovery();
      return null;
    }
    return value as RecoveryMetadata;
  } catch {
    clearRecovery();
    return null;
  }
}

export function saveRecovery(
  value: Omit<RecoveryMetadata, 'version' | 'savedAt' | 'expiresAt'>,
): void {
  const savedAt = Date.now();
  const metadata: RecoveryMetadata = {
    ...value,
    version: 1,
    savedAt,
    expiresAt: savedAt + RECOVERY_TTL_MS,
  };
  window.sessionStorage.setItem(RECOVERY_KEY, JSON.stringify(metadata));
}

export function clearRecovery(): void {
  window.sessionStorage.removeItem(RECOVERY_KEY);
}
