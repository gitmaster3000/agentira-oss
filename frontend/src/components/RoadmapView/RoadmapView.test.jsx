import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { format } from 'date-fns';
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
    CalendarBoard: ({ view, rangeStart, rangeEnd, onNavigate }) => (
        <div>
            <output>
                Calendar detail: {view} · range: {rangeStart && format(rangeStart, 'yyyy-MM-dd')}–
                {rangeEnd && format(rangeEnd, 'yyyy-MM-dd')}
            </output>
            <button type="button" onClick={() => onNavigate(new Date('2026-10-01T00:00:00'))}>
                Navigate shared schedule
            </button>
        </div>
    ),
}));

vi.mock('./ScheduleDateRangePicker', () => ({
    ScheduleDateRangePicker: ({ onChange }) => (
        <button
            type="button"
            onClick={() => onChange([
                new Date('2026-09-10T00:00:00'),
                new Date('2026-09-20T00:00:00'),
            ])}
        >
            Choose September range
        </button>
    ),
}));

const ROADMAP = {
    project: { id: 'p1', name: 'Agentira' },
    summary: {
        total_tasks: 2,
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
        total: 2,
        tasks: [{
            id: '9edb082ca059',
            key: 'AP-496',
            title: 'Improve project management',
            status: 'in_progress',
            priority: 'critical',
            progress: 25,
            start: '2026-08-06',
            end: '2026-08-07',
        }, {
            id: 'a89b4e7a8589',
            key: 'AP-501',
            title: 'Add due date to tasks',
            status: 'todo',
            priority: 'medium',
            progress: 0,
            // no end / due_date — undated (AP-501 filter coverage)
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

    it('uses the same selected range for the timeline and Day calendar mode', async () => {
        render(
            <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
                <Routes>
                    <Route path="/studio/project/:projectId/roadmap" element={<RoadmapView />} />
                </Routes>
            </MemoryRouter>,
        );

        fireEvent.click(await screen.findByRole('button', { name: 'Choose September range' }));
        expect(screen.getByText('No scheduled work falls inside this date range.')).toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: 'Day' }));

        expect(await screen.findByText(
            'Calendar detail: day · range: 2026-09-10–2026-09-20',
        )).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Navigate shared schedule' }));
        expect(await screen.findByText(
            'Calendar detail: day · range: 2026-10-01–2026-10-11',
        )).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Timeline' })).toHaveAttribute('aria-pressed', 'false');
        expect(screen.getByRole('button', { name: 'Day' })).toHaveAttribute('aria-pressed', 'true');
    });
});

describe('RoadmapView due-date filter (AP-501)', () => {
    it('filters timeline tasks by due date', async () => {
        render(
            <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
                <Routes>
                    <Route path="/studio/project/:projectId/roadmap" element={<RoadmapView />} />
                </Routes>
            </MemoryRouter>,
        );

        expect(await screen.findByTitle('Open AP-496 in full view')).toBeInTheDocument();
        expect(screen.getByTitle('Open AP-501 in full view')).toBeInTheDocument();

        fireEvent.change(screen.getByLabelText('Filter by due date'), {
            target: { value: 'has_due' },
        });
        expect(screen.getByTitle('Open AP-496 in full view')).toBeInTheDocument();
        expect(screen.queryByTitle('Open AP-501 in full view')).not.toBeInTheDocument();

        fireEvent.change(screen.getByLabelText('Filter by due date'), {
            target: { value: 'no_due' },
        });
        expect(screen.queryByTitle('Open AP-496 in full view')).not.toBeInTheDocument();
        expect(screen.getByTitle('Open AP-501 in full view')).toBeInTheDocument();
    });
});
