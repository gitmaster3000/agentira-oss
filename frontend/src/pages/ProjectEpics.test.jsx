import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ProjectEpics } from './ProjectEpics';
import { ProjectLayout } from './ProjectLayout';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getBoard: vi.fn(), getProjectMembers: vi.fn(), getProfiles: vi.fn(),
        getEpics: vi.fn(), getProjectActivity: vi.fn(),
    },
}));
vi.mock('../components/RoadmapView/RoadmapView', () => ({
    RoadmapView: () => <div>roadmap</div>,
}));

const EPICS = [
    { id: 'e1', title: 'Auth revamp', status: 'in_progress', assignee: 'ada', color: '#ff0000', task_count: 4 },
    { id: 'e2', title: 'Empty one', status: 'backlog', assignee: '', color: '#00ff00', task_count: 0 },
];

function mount(path) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/studio/project/:projectId" element={<ProjectLayout />}>
                    <Route path="calendar" element={<div data-testid="cal-route">cal</div>} />
                    <Route path="epics" element={<ProjectEpics />} />
                </Route>
                <Route path="/studio/epics/:id" element={<div>epic-page</div>} />
            </Routes>
        </MemoryRouter>
    );
}

function setup() {
    api.getBoard.mockResolvedValue({
        project: { id: 'p1', name: 'Atlas', key_prefix: 'ATL' },
        columns: { done: [{ id: 't1', epic_id: 'e1', status: 'done' }, { id: 't2', epic_id: 'e1', status: 'done' }], todo: [{ id: 't3', epic_id: 'e1', status: 'todo' }] },
    });
    api.getProjectMembers.mockResolvedValue([]);
    api.getProfiles.mockResolvedValue([]);
    api.getEpics.mockResolvedValue(EPICS);
    api.getProjectActivity.mockResolvedValue([]);
}

describe('Epics tab', () => {
    it('lists epics with progress, opens EpicPage, fires create-epic event', async () => {
        setup();
        mount('/studio/project/p1/epics');
        expect(await screen.findByText('Auth revamp')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Epics' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByText('@ada')).toBeInTheDocument();
        expect(screen.getByText('In progress')).toBeInTheDocument();
        expect(screen.getByText('2/4')).toBeInTheDocument();
        expect(screen.getByText('0/0')).toBeInTheDocument();
        const spy = vi.fn();
        window.addEventListener('open-create-epic', spy);
        fireEvent.click(screen.getByRole('button', { name: /New epic/ }));
        expect(spy).toHaveBeenCalled();
        window.removeEventListener('open-create-epic', spy);
        fireEvent.click(screen.getByText('Auth revamp'));
        expect(await screen.findByText('epic-page')).toBeInTheDocument();
    });
});

describe('Calendar tab', () => {
    it('does not show the board search on calendar', async () => {
        setup();
        mount('/studio/project/p1/calendar');
        await screen.findByRole('link', { name: 'Calendar' });
        expect(screen.queryByPlaceholderText('Search tasks…')).not.toBeInTheDocument();
    });

    it('is an enabled, active-highlighted link to the calendar route', async () => {
        setup();
        mount('/studio/project/p1/calendar');
        const tab = await screen.findByRole('link', { name: 'Calendar' });
        expect(tab).toHaveAttribute('href', '/studio/project/p1/calendar');
        expect(tab).toHaveAttribute('aria-current', 'page');
        expect(screen.getByTestId('cal-route')).toBeInTheDocument();
        expect(screen.getByText('Reports')).toHaveAttribute('aria-disabled', 'true');
    });
});
