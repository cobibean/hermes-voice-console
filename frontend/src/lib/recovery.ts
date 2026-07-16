const RECOVERY_KEY = 'hvc.recovery.v1';
const RECOVERY_TTL_MS = 2 * 60 * 60 * 1000;
const RECOVERY_IDENTIFIER_MAX = 128;

function isBoundedIdentifier(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= RECOVERY_IDENTIFIER_MAX
    && /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(value);
}

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
      || !isBoundedIdentifier(value.target)
      || !isBoundedIdentifier(value.conversationId)
      || !isBoundedIdentifier(value.runId)
      || !Number.isSafeInteger(value.lastSequence)
      || Number(value.lastSequence) < 0
      || typeof value.savedAt !== 'number'
      || typeof value.expiresAt !== 'number'
      || value.expiresAt - value.savedAt !== RECOVERY_TTL_MS
      || value.savedAt > Date.now() + 60_000
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
  if (
    !isBoundedIdentifier(value.target)
    || !isBoundedIdentifier(value.conversationId)
    || !isBoundedIdentifier(value.runId)
    || !Number.isSafeInteger(value.lastSequence)
    || value.lastSequence < 0
  ) {
    throw new Error('Recovery metadata must contain bounded identifiers and a non-negative cursor');
  }
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
