import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CreateEpicModal } from './CreateEpicModal';
import { api } from '../api';

vi.mock('../api', () => ({
    api: { createEpic: vi.fn() },
}));

function renderModal(props = {}) {
    return render(
        <MemoryRouter initialEntries={['/start']}>
            <Routes>
                <Route
                    path="/start"
                    element={<CreateEpicModal projectId="P1" onClose={() => {}} {...props} />}
                />
                <Route path="/studio/epics/:id" element={<div>EPIC DETAIL :id</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('CreateEpicModal', () => {
    beforeEach(() => vi.clearAllMocks());

    it('navigates to the new epic detail page after creation', async () => {
        api.createEpic.mockResolvedValue({ id: 'E42', title: 'Auth' });
        renderModal();

        fireEvent.change(screen.getByPlaceholderText('What are we aiming for?'), {
            target: { value: 'Auth' },
        });
        fireEvent.click(screen.getByRole('button', { name: /create epic/i }));

        await waitFor(() => expect(screen.getByText('EPIC DETAIL :id')).toBeInTheDocument());
        expect(api.createEpic).toHaveBeenCalledWith('P1', expect.objectContaining({ title: 'Auth' }));
    });

    it('passes the created epic to onCreated', async () => {
        api.createEpic.mockResolvedValue({ id: 'E1', title: 'Auth' });
        const onCreated = vi.fn();
        renderModal({ onCreated });

        fireEvent.change(screen.getByPlaceholderText('What are we aiming for?'), {
            target: { value: 'Auth' },
        });
        fireEvent.click(screen.getByRole('button', { name: /create epic/i }));

        await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ id: 'E1', title: 'Auth' }));
    });
});
