import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { RoadmapView } from './RoadmapView';
import { api } from '../../api';

vi.mock('../../api', () => ({
    api: {
        getRoadmap: vi.fn(),
        getProjectActivity: vi.fn(),
        removeDependency: vi.fn(),
    },
}));

vi.mock('./CalendarBoard', () => ({
    CalendarBoard: ({ view }) => <div>Calendar detail: {view}</div>,
}));

const ROADMAP = {
    project: { id: 'p1', name: 'Agentira' },
    summary: {
        total_tasks: 1,
        total_epics: 1,
        total_done: 0,
        total_milestones: 0,
        blocked_tasks: 0,
    },
    epics: [{
        id: 'e1',
        name: 'Launch',
        color: '#7c4dff',
        progress: 0,
        in_progress: 1,
        done: 0,
        total: 1,
        tasks: [{
            id: '9edb082ca059',
            key: 'AP-496',
            title: 'Improve project management',
            status: 'in_progress',
            priority: 'critical',
            progress: 25,
        }],
    }],
    dependencies: [],
    milestones: [],
    recent_completions: [],
};

function TaskDestination() {
    const { taskId } = useParams();
    return <div>Full task {taskId}</div>;
}

beforeEach(() => {
    vi.clearAllMocks();
    api.getRoadmap.mockResolvedValue(ROADMAP);
    api.getProjectActivity.mockResolvedValue([]);
});

describe('RoadmapView navigation', () => {
    it('uses one Schedule view and opens timeline tasks in full view by key', async () => {
        render(
            <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
                <Routes>
                    <Route path="/studio/project/:projectId/roadmap" element={<RoadmapView />} />
                    <Route path="/studio/tasks/:taskId" element={<TaskDestination />} />
                </Routes>
            </MemoryRouter>,
        );

        expect(await screen.findByRole('button', { name: 'Schedule' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Calendar' })).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Dependencies' })).toBeInTheDocument();
        fireEvent.click(screen.getByTitle('Open AP-496 in full view'));
        expect(screen.getByText('Full task AP-496')).toBeInTheDocument();
    });

    it('switches from the timeline to calendar detail inside Schedule', async () => {
        render(
            <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
                <Routes>
                    <Route path="/studio/project/:projectId/roadmap" element={<RoadmapView />} />
                </Routes>
            </MemoryRouter>,
        );

        fireEvent.click(await screen.findByRole('button', { name: 'Month' }));

        expect(await screen.findByText('Calendar detail: month')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Timeline' })).toHaveAttribute('aria-pressed', 'false');
        expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true');
    });
});
