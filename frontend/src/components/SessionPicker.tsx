export function SessionPicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>Session key</span>
      <input aria-label="Session key" value={value} onChange={(event) => onChange(event.target.value)} placeholder="voice-console:agent" />
    </label>
  );
}
