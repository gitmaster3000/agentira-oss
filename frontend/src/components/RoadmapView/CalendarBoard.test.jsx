import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { format } from 'date-fns';
import { CalendarBoard } from './CalendarBoard';

vi.mock('react-big-calendar', () => ({
    dateFnsLocalizer: () => ({}),
    Calendar: ({ events, onSelectEvent, date }) => {
        const task = events.find(event => event.kind === 'task');
        return (
            <div>
                <output data-testid="calendar-date">{format(date, 'yyyy-MM-dd')}</output>
                {task && (
                    <button type="button" onClick={() => onSelectEvent(task)}>
                        {task.title}
                    </button>
                )}
            </div>
        );
    },
}));

const EPICS = [{
    name: 'Launch',
    tasks: [{
        id: '9edb082ca059',
        key: 'AP-496',
        title: 'Improve project management',
        status: 'in_progress',
        start: '2026-08-06',
        end: '2026-08-07',
    }],
}];

function TaskDestination() {
    const { taskId } = useParams();
    return <div>Full task {taskId}</div>;
}

function renderCalendar() {
    return render(
        <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
            <Routes>
                <Route path="/studio/project/:projectId/roadmap" element={<CalendarBoard epics={EPICS} />} />
                <Route path="/studio/tasks/:taskId" element={<TaskDestination />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('CalendarBoard', () => {
    it('opens a task full-screen using its short key', () => {
        renderCalendar();

        fireEvent.click(screen.getByRole('button', { name: /AP-496 Improve project management/ }));

        expect(screen.getByText('Full task AP-496')).toBeInTheDocument();
    });

    it('lets users jump directly to a selected date', () => {
        renderCalendar();

        fireEvent.change(screen.getByLabelText('Jump to date'), {
            target: { value: '2027-04-05' },
        });

        expect(screen.getByTestId('calendar-date')).toHaveTextContent('2027-04-05');
    });
});
