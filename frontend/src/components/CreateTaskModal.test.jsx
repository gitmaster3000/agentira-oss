import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CreateTaskModal } from './CreateTaskModal';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        createTask: vi.fn(),
        createEpic: vi.fn(),
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
                <Route path="/studio/epics/:id" element={<div>EPIC DETAIL</div>} />
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
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));

        await waitFor(() => expect(screen.getByText('TASK DETAIL')).toBeInTheDocument());
        expect(api.createTask).toHaveBeenCalledWith(
            expect.objectContaining({ project_id: 'P1', title: 'Build it' }),
        );
    });

    it('type switch creates a bug with type=bug', async () => {
        api.createTask.mockResolvedValue({ id: 'T1', key: 'AP-1' });
        const onCreated = vi.fn();
        renderModal({ onCreated });

        fireEvent.click(screen.getByRole('radio', { name: 'Bug' }));
        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Crash on save' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create' }));

        await waitFor(() => expect(api.createTask).toHaveBeenCalled());
        expect(api.createTask.mock.calls[0][0]).toMatchObject({ type: 'bug', title: 'Crash on save' });
        await waitFor(() => expect(onCreated).toHaveBeenCalled());
    });

    it('bug prefills description once, without clobbering typed text', async () => {
        renderModal();
        fireEvent.click(screen.getByRole('radio', { name: 'Bug' }));
        expect(screen.getByLabelText('Description').value).toMatch(/Expected/);
        fireEvent.click(screen.getByRole('radio', { name: 'Task' }));
        fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'mine' } });
        fireEvent.click(screen.getByRole('radio', { name: 'Bug' }));
        expect(screen.getByLabelText('Description').value).toBe('mine');
    });

    it('epic type hides task-only fields and creates an epic', async () => {
        api.createEpic.mockResolvedValue({ id: 'E1' });
        renderModal();

        fireEvent.click(screen.getByRole('radio', { name: 'Epic' }));
        expect(screen.queryByLabelText('Priority')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('Assignee')).not.toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Launch' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create' }));

        await waitFor(() => expect(api.createEpic).toHaveBeenCalledWith('P1', expect.objectContaining({ title: 'Launch' })));
        expect(api.createTask).not.toHaveBeenCalled();
        expect(await screen.findByText('EPIC DETAIL')).toBeInTheDocument();
    });
});
