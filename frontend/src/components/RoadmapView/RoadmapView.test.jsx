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
    it('uses the Dependencies label and opens timeline tasks in full view by key', async () => {
        render(
            <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
                <Routes>
                    <Route path="/studio/project/:projectId/roadmap" element={<RoadmapView />} />
                    <Route path="/studio/tasks/:taskId" element={<TaskDestination />} />
                </Routes>
            </MemoryRouter>,
        );

        expect(await screen.findByRole('button', { name: 'Dependencies' })).toBeInTheDocument();
        fireEvent.click(screen.getByTitle('Open AP-496 in full view'));
        expect(screen.getByText('Full task AP-496')).toBeInTheDocument();
    });
});
