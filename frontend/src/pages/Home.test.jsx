import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Home } from './Home';
import { api } from '../api';

vi.mock('../api', () => ({
    api: { getHome: vi.fn(), getHomeLayout: vi.fn(), saveHomeLayout: vi.fn() },
}));
vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ user: { display_name: 'Alex Rivera' } }),
}));
vi.mock('../components/CreateProjectWizard', () => ({
    CreateProjectWizard: () => <div>wizard</div>,
}));

const project = (i, extra = {}) => ({
    id: `p${i}`, name: `Project ${i}`, key: `P${i}`, colour: '#c9b8ff', description: 'Desc',
    pct_done: 40, open: 5, due_this_week: 2, late: 1,
    members: [{ id: 'm1', name: 'ali', display_name: 'Ali', avatar_url: '' }], member_count: 7,
    last_updated: new Date().toISOString(), done_per_week: [1, 2, 3, 4, 5, 6], ...extra,
});
const HOME = {
    week: { done: 17, due: 9, late: 3, planned: 29 },
    projects: [project(1), project(2)],
    activity: [{ id: 'a1', actor: 'mohsin', action: 'task.move', detail: '', task_key: 'KE-28', task_title: 'Quiz rules',
        project_id: 'p1', project_name: 'Project 1', at: new Date().toISOString() }],
    people: [{ name: 'mohsin', open: 6, days_done_this_week: 3 }],
    week_summary: 'Going well.',
};

function renderHome() {
    return render(
        <MemoryRouter initialEntries={['/']}>
            <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/studio/project/:id/overview" element={<div>overview page</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('Home', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getHome.mockResolvedValue(HOME);
        api.getHomeLayout.mockResolvedValue({ layout: [] });
        api.saveHomeLayout.mockResolvedValue({});
    });

    it('renders hero headline, summary, rings and makes one data request', async () => {
        renderHome();
        expect(await screen.findByText(/, Alex$/)).toBeInTheDocument();
        expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/^Good (morning|afternoon|evening)/);
        expect(screen.getByText('3 tasks past due. Start there.')).toBeInTheDocument();
        expect(screen.getByText('Going well.')).toBeInTheDocument();
        expect(screen.getByLabelText('Done: 17 of 29 tasks this week')).toBeInTheDocument();
        expect(screen.getByText('29 tasks')).toBeInTheDocument();
        expect(api.getHome).toHaveBeenCalledTimes(1);
        expect(api.getHomeLayout).toHaveBeenCalledTimes(1);
    });

    it('hides the summary when null', async () => {
        api.getHome.mockResolvedValue({ ...HOME, week_summary: null });
        renderHome();
        await screen.findByText(/, Alex$/);
        expect(document.querySelector('.home-summary')).toBeNull();
    });

    it('shows an error state when Home fails to load', async () => {
        api.getHome.mockRejectedValue(new Error('boom'));
        renderHome();
        expect(await screen.findByRole('alert')).toHaveTextContent('boom');
    });

    it('project card shows stats and opens the project Overview', async () => {
        renderHome();
        const card = await screen.findByRole('button', { name: 'Open Project 1' });
        expect(within(card).getByText('+6')).toBeInTheDocument();
        expect(within(card).getByText('late')).toBeInTheDocument();
        fireEvent.click(card);
        expect(await screen.findByText('overview page')).toBeInTheDocument();
    });

    it('caps project cards and expands with All N projects', async () => {
        api.getHome.mockResolvedValue({ ...HOME, projects: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => project(i)) });
        renderHome();
        await screen.findByRole('button', { name: 'Open Project 1' });
        expect(screen.queryByRole('button', { name: 'Open Project 7' })).toBeNull();
        fireEvent.click(screen.getByText('All 8 projects'));
        expect(screen.getByRole('button', { name: 'Open Project 8' })).toBeInTheDocument();
    });

    it('uses a saved layout and falls back to the default when empty', async () => {
        api.getHomeLayout.mockResolvedValue({ layout: [['people', 's'], ['bogus', 'm']] });
        renderHome();
        await screen.findByText('People');
        await waitFor(() => expect(screen.queryByText('Activity')).toBeNull());
    });

    it('customize: resize, reorder, remove, add and reset persist via PUT', async () => {
        renderHome();
        await screen.findByText('Projects');
        fireEvent.click(screen.getByRole('button', { name: 'Customize home' }));

        fireEvent.click(within(screen.getByText('Activity').closest('section')).getByText('Third'));
        expect(api.saveHomeLayout).toHaveBeenLastCalledWith([['projects', 'l'], ['activity', 's'], ['people', 'm']]);

        fireEvent.click(screen.getByLabelText('Move People earlier'));
        expect(api.saveHomeLayout).toHaveBeenLastCalledWith([['projects', 'l'], ['people', 'm'], ['activity', 's']]);

        fireEvent.click(screen.getByLabelText('Remove People'));
        expect(api.saveHomeLayout).toHaveBeenLastCalledWith([['projects', 'l'], ['activity', 's']]);

        fireEvent.click(screen.getByText('Add tile'));
        fireEvent.click(within(screen.getByRole('dialog')).getByText('Add'));
        expect(api.saveHomeLayout).toHaveBeenLastCalledWith([['projects', 'l'], ['activity', 's'], ['people', 'm']]);

        fireEvent.click(screen.getByText('Reset to default'));
        expect(api.saveHomeLayout).toHaveBeenLastCalledWith([['projects', 'l'], ['activity', 'm'], ['people', 'm']]);

        fireEvent.click(screen.getByRole('button', { name: 'Done' }));
        expect(screen.queryByText('Reset to default')).toBeNull();
    });

    it('New project opens the wizard', async () => {
        renderHome();
        fireEvent.click(await screen.findByText('New project'));
        expect(screen.getByText('wizard')).toBeInTheDocument();
    });
});
