import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BranchPrSection } from './BranchPrSection';
import { api } from '../../api';

vi.mock('../../api', () => ({ api: { updateTask: vi.fn(() => Promise.resolve({})) } }));

const task = { id: 'T1', branch: 'old', pr_url: '' };
const setup = (onSaved = vi.fn()) => {
    render(<BranchPrSection task={task} commits={[]} open onToggle={() => {}} onSaved={onSaved} />);
    fireEvent.click(screen.getByTitle('Edit'));
    return { input: screen.getByRole('textbox'), onSaved };
};

describe('BranchPrSection inline edit', () => {
    beforeEach(() => vi.clearAllMocks());

    it('saves once when Enter is followed by blur', async () => {
        const { input, onSaved } = setup();
        fireEvent.change(input, { target: { value: 'new' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        fireEvent.blur(input);
        await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
        expect(api.updateTask).toHaveBeenCalledTimes(1);
        expect(api.updateTask).toHaveBeenCalledWith('T1', { branch: 'new' });
        expect(screen.queryByRole('textbox')).toBeNull();
    });

    it('stays open and shows the error when the save fails', async () => {
        api.updateTask.mockRejectedValueOnce(new Error('server said no'));
        const { input } = setup();
        fireEvent.change(input, { target: { value: 'new' } });
        fireEvent.blur(input);
        expect(await screen.findByRole('alert')).toHaveTextContent('server said no');
        expect(screen.getByRole('textbox').value).toBe('new');
    });

    it('Escape cancels without saving', () => {
        const { input } = setup();
        fireEvent.change(input, { target: { value: 'new' } });
        fireEvent.keyDown(input, { key: 'Escape' });
        fireEvent.blur(input);
        expect(api.updateTask).not.toHaveBeenCalled();
        expect(screen.queryByRole('textbox')).toBeNull();
        expect(screen.getByText('old')).toBeInTheDocument();
    });
});
