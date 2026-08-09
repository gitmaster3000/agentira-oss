import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { TaskCard } from './TaskCard';

vi.mock('../api', () => ({ api: { deleteTask: vi.fn() } }));

function renderCard(task) {
    return render(
        <MemoryRouter>
            <TaskCard task={task} onUpdate={() => {}} onDelete={() => {}} />
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
});
