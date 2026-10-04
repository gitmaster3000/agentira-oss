import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestedBy } from './TestedBy';
import { api } from '../../api';

vi.mock('../../api', () => ({
    api: {
        getTaskProof: vi.fn(),
        downloadAttachment: vi.fn(() => Promise.resolve()),
    },
}));

describe('TestedBy', () => {
    beforeEach(() => vi.clearAllMocks());

    it('names who tested it and opens the proof', async () => {
        api.getTaskProof.mockResolvedValue({
            present: true, tested_by: 'Frontend Dev',
            attachment_id: 'A1', filename: 'proof-AP-1.md',
        });
        render(<TestedBy taskId="T1" />);
        expect(await screen.findByText(/Tested by Frontend Dev/)).toBeInTheDocument();
        fireEvent.click(screen.getByText('see proof'));
        await waitFor(() => expect(api.downloadAttachment)
            .toHaveBeenCalledWith('A1', 'proof-AP-1.md'));
    });

    it('says plainly when nobody has tested it yet', async () => {
        api.getTaskProof.mockResolvedValue({ present: false, stale: false });
        render(<TestedBy taskId="T1" />);
        expect(await screen.findByText('Not tested yet — no proof attached.')).toBeInTheDocument();
    });

    it('says when the proof is out of date', async () => {
        api.getTaskProof.mockResolvedValue({ present: false, stale: true });
        render(<TestedBy taskId="T1" />);
        expect(await screen.findByText(/Changed since it was last tested/)).toBeInTheDocument();
    });

    it('renders nothing when the proof cannot be loaded', async () => {
        api.getTaskProof.mockRejectedValue(new Error('boom'));
        const { container } = render(<TestedBy taskId="T1" />);
        await waitFor(() => expect(api.getTaskProof).toHaveBeenCalled());
        expect(container).toBeEmptyDOMElement();
    });
});
