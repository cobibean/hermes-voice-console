import type { TargetInfo } from '../lib/types';

export function TargetPicker({ targets, value, onChange }: { targets: TargetInfo[]; value: string; onChange: (name: string) => void }) {
  return (
    <label className="field">
      <span>Target agent</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} aria-label="Target agent">
        {targets.map((target) => (
          <option key={target.name} value={target.name}>{target.label}{target.api_key_configured ? '' : ' (missing key)'}</option>
        ))}
      </select>
    </label>
  );
}
