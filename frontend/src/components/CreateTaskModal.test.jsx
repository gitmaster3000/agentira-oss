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

    it('applies a task template to the Definition of Done', async () => {
        renderModal();

        const select = await screen.findByLabelText('Template');
        fireEvent.change(select, { target: { value: 'professionalization' } });

        expect(screen.getByText('Unit tests')).toBeInTheDocument();
        expect(screen.getByText('Bruno integration tests')).toBeInTheDocument();
        expect(screen.getByText('Manual test description attached')).toBeInTheDocument();
    });

    it('prefills task fields (description, priority) from the template', async () => {
        renderModal();

        const select = await screen.findByLabelText('Template');
        fireEvent.change(select, { target: { value: 'professionalization' } });

        const description = screen.getByLabelText('Description');
        expect(description.value).toMatch(/production/i);
        expect(screen.getByLabelText('Priority').value).toBe('high');
    });

    it('does not overwrite a description the user already typed', async () => {
        renderModal();
        const description = screen.getByLabelText('Description');
        fireEvent.change(description, { target: { value: 'my own notes' } });

        const select = await screen.findByLabelText('Template');
        fireEvent.change(select, { target: { value: 'professionalization' } });

        expect(description.value).toBe('my own notes');
    });

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
