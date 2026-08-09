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

    it('task template button prefills task fields but not the DoD', async () => {
        renderModal();

        fireEvent.click(await screen.findByRole('button', { name: 'Task template: Professionalization' }));

        expect(screen.getByLabelText('Description').value).toMatch(/production/i);
        expect(screen.getByLabelText('Priority').value).toBe('high');
        // No DoD items added by a task template.
        expect(screen.queryByText('Unit tests')).not.toBeInTheDocument();
    });

    it('does not overwrite a description the user already typed', async () => {
        renderModal();
        const description = screen.getByLabelText('Description');
        fireEvent.change(description, { target: { value: 'my own notes' } });

        fireEvent.click(await screen.findByRole('button', { name: 'Task template: Professionalization' }));

        expect(description.value).toBe('my own notes');
    });

    it('DoD template toggles its items on and off and stays out of task fields', async () => {
        renderModal();
        const btn = await screen.findByRole('button', { name: 'DoD template: Professionalization' });

        fireEvent.click(btn);
        expect(screen.getByText('Unit tests')).toBeInTheDocument();
        expect(screen.getByText('Bruno integration tests')).toBeInTheDocument();
        expect(btn).toHaveAttribute('aria-pressed', 'true');
        // DoD template must not fill task content.
        expect(screen.getByLabelText('Description').value).toBe('');

        fireEvent.click(btn);
        expect(screen.queryByText('Unit tests')).not.toBeInTheDocument();
        expect(btn).toHaveAttribute('aria-pressed', 'false');
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
