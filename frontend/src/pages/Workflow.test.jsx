import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Workflow } from './Workflow';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getBoard: vi.fn(),
        getProjectWorkflow: vi.fn(),
    },
}));

const BOARD = {
    project: { id: 'P1', name: 'Proj' },
    columns: {
        backlog: [],
        todo: [{ id: 't1' }],
        in_progress: [{ id: 't2' }, { id: 't3' }],
        review: [],
        done: [],
    },
};

const FLOW = {
    columns: [
        { name: 'backlog' },
        { name: 'todo' },
        { name: 'in_progress', on_success: { advance_to: 'review', assign_role: 'reviewer', dispatch: true } },
        { name: 'review', on_success: { advance_to: 'done', integrate: { target_branch: 'main', push: true } } },
        { name: 'done', on_enter: { dispatch_role: 'documentation' } },
    ],
    roles: {},
    bounce: { enabled: true, max_attempts: 2, window_minutes: 30 },
    rejection: { enabled: true },
};

// Real gate checks + prompts, as the backend's columns_ui payload delivers them.
const COLUMNS_UI = {
    backlog: { advance_to: null, gates: [], prompt_role: null, prompt: '' },
    todo: { advance_to: null, gates: [], prompt_role: null, prompt: '' },
    in_progress: {
        advance_to: 'review',
        gates: [
            { name: 'dod_all_checked', description: 'Every Definition-of-Done item is checked.' },
            { name: 'has_branch_or_pr', description: 'Task has a branch or a PR URL.' },
        ],
        prompt_role: null,
        prompt: '',
    },
    review: { advance_to: 'done', gates: [], prompt_role: 'reviewer', prompt_slug: 'reviewer', prompt: 'Review the branch and approve.', prompt_is_override: false },
    done: { advance_to: null, gates: [], prompt_role: 'documentation', prompt_slug: 'documentation', prompt: 'Document the change.', prompt_is_override: false },
};

function renderWorkflow() {
    return render(
        <MemoryRouter initialEntries={['/studio/project/P1/workflow']}>
            <Routes>
                <Route path="/studio/project/:projectId/workflow" element={<Workflow />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('Workflow Engine page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getBoard.mockResolvedValue(BOARD);
        api.getProjectWorkflow.mockResolvedValue({ workflow_enabled: true, flow: FLOW, columns_ui: COLUMNS_UI, editable: [] });
    });

    it('renders every board column and its live count', async () => {
        renderWorkflow();
        expect(await screen.findByRole('heading', { name: 'Workflow Engine' })).toBeInTheDocument();
        expect(screen.getByText('todo')).toBeInTheDocument();
        expect(screen.getByText('in_progress')).toBeInTheDocument();
        expect(screen.getByText('done')).toBeInTheDocument();
        // todo has 1 task in BOARD — shown as its tile count
        expect(screen.getByText('1')).toBeInTheDocument();
    });

    it('defaults to selecting the first column and shows its process + gate in the side panel', async () => {
        renderWorkflow();
        await screen.findByRole('heading', { name: 'Workflow Engine' });
        expect(screen.getByText(/Process · on enter/i)).toBeInTheDocument();
        expect(screen.getByText(/Gate · on exit/i)).toBeInTheDocument();
    });

    it('selecting a column shows its REAL gate checks from the backend', async () => {
        renderWorkflow();
        await screen.findByText('in_progress');
        fireEvent.click(screen.getByText('in_progress'));
        expect(await screen.findByText('task.dod_all_checked')).toBeInTheDocument();
        expect(screen.getByText(/Every Definition-of-Done item is checked/i)).toBeInTheDocument();
    });

    it('shows the template prompt for a column that dispatches a role', async () => {
        renderWorkflow();
        await screen.findByText('review');
        fireEvent.click(screen.getByText('review'));
        expect(await screen.findByText(/role: reviewer/i)).toBeInTheDocument();
        expect(screen.getByText('Review the branch and approve.')).toBeInTheDocument();
    });

    it('the Code toggle shows the read-only Starlark for the selected column', async () => {
        renderWorkflow();
        await screen.findByText('in_progress');
        fireEvent.click(screen.getByText('in_progress'));
        fireEvent.click(screen.getByText('Code'));
        expect(await screen.findByText('in_progress.star')).toBeInTheDocument();
        expect(screen.getByText(/def validate_transition/)).toBeInTheDocument();
    });
});
