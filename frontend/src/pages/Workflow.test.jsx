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
        api.getProjectWorkflow.mockResolvedValue({ workflow_enabled: true, flow: FLOW, editable: [] });
    });

    it('renders the engine card with every board column and its live count', async () => {
        renderWorkflow();
        expect(await screen.findByRole('heading', { name: 'Workflow Engine' })).toBeInTheDocument();
        expect(screen.getByText('todo')).toBeInTheDocument();
        expect(screen.getByText('in_progress')).toBeInTheDocument();
        expect(screen.getByText('done')).toBeInTheDocument();
        // todo has 1 task in BOARD — shown as its tile count
        expect(screen.getByText('1')).toBeInTheDocument();
    });

    it('defaults to selecting the first column and shows its process + gate zones', async () => {
        renderWorkflow();
        await screen.findByRole('heading', { name: 'Workflow Engine' });
        expect(screen.getByText(/backlog · process/i)).toBeInTheDocument();
        expect(screen.getByText(/backlog · gate/i)).toBeInTheDocument();
    });

    it('selecting a column updates the gate to that column\'s conditions', async () => {
        renderWorkflow();
        await screen.findByText('in_progress');
        fireEvent.click(screen.getByText('in_progress'));
        expect(await screen.findByText('task.dod_all_checked')).toBeInTheDocument();
        expect(screen.getByText(/all DoD items must be checked/i)).toBeInTheDocument();
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
