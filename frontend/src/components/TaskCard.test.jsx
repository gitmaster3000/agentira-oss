import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TaskCard } from './TaskCard';
import { api } from '../api';

vi.mock('../api', () => ({ api: { deleteTask: vi.fn(), updateTask: vi.fn(), } }));

function renderCard(task, epics = []) {
    return render(
        <MemoryRouter>
            <TaskCard task={task} epics={epics} onUpdate={() => {}} onDelete={() => {}} />
        </MemoryRouter>,
    );
}

const base = { id: 'T1', key: 'AP-1', title: 'My task', priority: 'critical' };

describe('TaskCard', () => {
    it('does not tint the left border with the priority color', () => {
        const { container } = renderCard(base);
        const card = container.firstChild;
        // Critical's color is #f85149 — it must not bleed into the left edge.
        expect(card.style.borderLeft).not.toContain('248'); // rgb of #f85149
        expect(card.style.borderLeft).toContain('var(--border-subtle)');
        // Priority still readable via its pill.
        expect(screen.getByText('critical')).toBeInTheDocument();
    });

    it('keeps the live-agent indicator on the left border when active', () => {
        const { container } = renderCard({ ...base, agent_active: true });
        // The live accent is themed — it resolves per day/night palette.
        expect(container.firstChild.style.borderLeft).toContain('var(--pulse-blue)');
    });

    describe('epic dropdown', () => {
        const epicTask = { ...base, project_id: 'P1', epic_id: 'E1', epic_name: 'Onboarding', epic_color: '#7c4dff' };
        const epics = [{ id: 'E1', title: 'Onboarding', color: '#7c4dff' }, { id: 'E2', title: 'Billing', color: '#2ecc71' }];
        beforeEach(() => { vi.clearAllMocks() });

        it('changes epic optimistically and saves via updateTask', async () => {
            let resolve;
            api.updateTask.mockReturnValue(new Promise(r => { resolve = r; }));
            renderCard(epicTask, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            fireEvent.click(await screen.findByRole('menuitemradio', { name: 'Billing' }));
            // Shown before the request settles.
            expect(screen.getByLabelText('Epic')).toHaveTextContent('Billing');
            expect(api.updateTask).toHaveBeenCalledWith('T1', { epic_id: 'E2' });
            resolve({});
        });

        it('rolls back when the save fails', async () => {
            vi.spyOn(window, 'alert').mockImplementation(() => {});
            api.updateTask.mockRejectedValue(new Error('nope'));
            renderCard(epicTask, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            fireEvent.click(await screen.findByRole('menuitemradio', { name: 'Billing' }));
            await waitFor(() => expect(screen.getByLabelText('Epic')).toHaveTextContent('Onboarding'));
        });

        it('closes on Escape and on outside click', () => {
            renderCard(epicTask, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            expect(screen.getByRole('menu')).toBeInTheDocument();
            fireEvent.keyDown(document, { key: 'Escape' });
            expect(screen.queryByRole('menu')).toBeNull();
            fireEvent.click(screen.getByLabelText('Epic'));
            fireEvent.mouseDown(document.body);
            expect(screen.queryByRole('menu')).toBeNull();
        });

        it('Remove clears the epic; Open epic links to it', async () => {
            api.updateTask.mockResolvedValue({});
            renderCard(epicTask, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            expect(screen.getByRole('menuitem', { name: 'Open epic' })).toHaveAttribute('href', expect.stringContaining('E1'));
            fireEvent.click(screen.getByRole('menuitem', { name: 'Remove' }));
            expect(api.updateTask).toHaveBeenCalledWith('T1', { epic_id: '' });
            expect(screen.getByLabelText('Epic')).toHaveTextContent('Add epic');
        });

        it('hides Open epic and Remove when the task has no epic', () => {
            renderCard(base, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            expect(screen.queryByRole('menuitem', { name: 'Open epic' })).toBeNull();
            expect(screen.queryByRole('menuitem', { name: 'Remove' })).toBeNull();
        });

        it('ticks the current epic; picking it again closes without saving', () => {
            renderCard(epicTask, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            const current = screen.getByRole('menuitemradio', { name: 'Onboarding' });
            expect(current).toHaveAttribute('aria-checked', 'true');
            expect(screen.getByRole('menuitemradio', { name: 'Billing' })).toHaveAttribute('aria-checked', 'false');
            fireEvent.click(current);
            expect(screen.queryByRole('menu')).toBeNull();
            expect(api.updateTask).not.toHaveBeenCalled();
        });

        it('filters a long epic list by search', () => {
            const many = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon', 'Zeta'].map((t, i) => ({ id: `X${i}`, title: t }));
            renderCard(base, many);
            fireEvent.click(screen.getByLabelText('Epic'));
            fireEvent.change(screen.getByPlaceholderText('Find an epic…'), { target: { value: 'ta' } });
            expect(screen.getAllByRole('menuitemradio').map(el => el.textContent)).toEqual(['Beta', 'Delta', 'Zeta']);
        });

        it('stays open when the epic list scrolls, closes when the page scrolls', () => {
            renderCard(epicTask, epics);
            fireEvent.click(screen.getByLabelText('Epic'));
            fireEvent.scroll(screen.getByRole('menu'));
            expect(screen.getByRole('menu')).toBeInTheDocument();
            fireEvent.scroll(window);
            expect(screen.queryByRole('menu')).toBeNull();
        });
    });
});
