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
        listTasks: vi.fn(() => Promise.resolve([
            { id: 'T7', key: 'AP-7', title: 'Auth setup', tags: ['frontend', 'urgent'] },
        ])),
        addTaskLink: vi.fn(),
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

        fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'bug' } });
        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Crash on save' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create' }));

        await waitFor(() => expect(api.createTask).toHaveBeenCalled());
        expect(api.createTask.mock.calls[0][0]).toMatchObject({ type: 'bug', title: 'Crash on save' });
        await waitFor(() => expect(onCreated).toHaveBeenCalled());
    });

    it('has no template pills and bug does not prefill the description', () => {
        renderModal();
        fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'bug' } });
        expect(screen.getByLabelText('Description').value).toBe('');
        expect(screen.queryByRole('button', { name: /template/i })).not.toBeInTheDocument();
    });

    it('epic type hides task-only fields and creates an epic', async () => {
        api.createEpic.mockResolvedValue({ id: 'E1' });
        renderModal();

        fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'epic' } });
        expect(screen.queryByLabelText('Priority')).not.toBeInTheDocument();
        expect(screen.getByLabelText('Assignee')).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Launch' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create' }));

        await waitFor(() => expect(api.createEpic).toHaveBeenCalledWith('P1', expect.objectContaining({ title: 'Launch', assignee: '' })));
        expect(api.createTask).not.toHaveBeenCalled();
        expect(await screen.findByText('EPIC DETAIL')).toBeInTheDocument();
    });

    it('suggests existing tags, links a task, sets due date and accepts dropped files', async () => {
        api.createTask.mockResolvedValue({ id: 'T1', key: 'AP-1' });
        renderModal();
        await waitFor(() => expect(api.listTasks).toHaveBeenCalledWith('P1'));

        fireEvent.change(screen.getByLabelText('Tags'), { target: { value: 'fro' } });
        fireEvent.click(await screen.findByRole('option', { name: 'frontend' }));

        fireEvent.change(screen.getByLabelText('Link type'), { target: { value: 'depends_on' } });
        fireEvent.change(screen.getByLabelText('Link task'), { target: { value: 'auth' } });
        fireEvent.click(await screen.findByRole('option', { name: /Auth setup/ }));

        fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-12-01' } });
        const file = new File(['x'], 'spec.txt', { type: 'text/plain' });
        fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [file] } });
        expect(screen.getByText('spec.txt')).toBeInTheDocument();

        fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Ship' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create' }));

        await waitFor(() => expect(api.addTaskLink).toHaveBeenCalledWith('T1', 'T7', 'depends_on'));
        expect(api.createTask.mock.calls[0][0]).toMatchObject({ tags: ['frontend'], due_date: '2026-12-01' });
        expect(api.uploadAttachment).toHaveBeenCalledWith('T1', file);
    });
});
