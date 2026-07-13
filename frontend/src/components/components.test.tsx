import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApprovalModal } from './ApprovalModal';
import { TargetPicker } from './TargetPicker';

describe('components', () => {
  it('renders target labels and missing-key status', async () => {
    const onChange = vi.fn();
    render(<TargetPicker targets={[{ name: 'a', label: 'Agent A', preferred_transport: 'runs', api_key_configured: false }]} value="a" onChange={onChange} />);
    expect(screen.getByRole('combobox', { name: /target agent/i })).toHaveTextContent('Agent A (missing key)');
  });

  it('approval modal emits deny decision', async () => {
    const onResolve = vi.fn();
    render(<ApprovalModal approval={{ runId: 'r1', message: 'Approve fake action?', choices: ['deny'], payload: { message: 'Approve fake action?', choices: ['deny'] } }} onResolve={onResolve} />);
    await userEvent.click(screen.getByRole('button', { name: /deny/i }));
    expect(onResolve).toHaveBeenCalledWith('deny');
  });

  it('requires a second confirmation for a permanent approval', async () => {
    const onResolve = vi.fn();
    render(<ApprovalModal approval={{ runId: 'r2', message: 'Persist command?', choices: ['always'], payload: { allow_permanent: true } }} onResolve={onResolve} />);
    await userEvent.click(screen.getByRole('button', { name: 'Permanently allow' }));
    expect(onResolve).not.toHaveBeenCalled();
    expect(screen.getByText(/permanently changes/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Confirm permanent allow' }));
    expect(onResolve).toHaveBeenCalledWith('always');
  });
});
