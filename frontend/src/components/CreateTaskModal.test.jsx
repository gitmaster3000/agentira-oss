import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CreateTaskModal } from './CreateTaskModal';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        createTask: vi.fn(),
        getProjectMembers: vi.fn(() => Promise.resolve([])),
        getEpics: vi.fn(() => Promise.resolve([])),
        uploadAttachment: vi.fn(),
    },
}));

function renderModal(props = {}) {
    return render(
        <MemoryRouter initialEntries={['/start']}>
            <Routes>
                <Route
                    path="/start"
                    element={<CreateTaskModal projectId="P1" onClose={() => {}} onCreated={() => {}} {...props} />}
                />
                <Route path="/studio/tasks/:id" element={<div>TASK DETAIL</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('CreateTaskModal', () => {
    beforeEach(() => vi.clearAllMocks());

    it('navigates to the new task detail page (by key) after creation', async () => {
        api.createTask.mockResolvedValue({ id: 'T1', key: 'AP-9' });
        renderModal();

        const titleInput = (await screen.findAllByRole('textbox'))[0];
        fireEvent.change(titleInput, { target: { value: 'Build it' } });
        fireEvent.click(screen.getByRole('button', { name: /create task/i }));

        await waitFor(() => expect(screen.getByText('TASK DETAIL')).toBeInTheDocument());
        expect(api.createTask).toHaveBeenCalledWith(
            expect.objectContaining({ project_id: 'P1', title: 'Build it' }),
        );
    });
});
