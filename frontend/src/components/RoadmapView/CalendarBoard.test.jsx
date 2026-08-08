import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { format } from 'date-fns';
import { CalendarBoard } from './CalendarBoard';

vi.mock('react-big-calendar', () => ({
    dateFnsLocalizer: () => ({}),
    Calendar: ({ events, onSelectEvent, date, view }) => {
        const task = events.find(event => event.kind === 'task');
        return (
            <div>
                <output data-testid="calendar-date">{format(date, 'yyyy-MM-dd')}</output>
                <output data-testid="calendar-view">{view}</output>
                {events.filter(event => event.kind === 'task').map(event => (
                    <output key={event.id} data-testid={`event-dates-${event.id}`}>
                        {format(event.start, 'yyyy-MM-dd')}–{format(event.end, 'yyyy-MM-dd')}
                    </output>
                ))}
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
    }, {
        id: 'due-only',
        title: 'Due on launch day',
        status: 'todo',
        start: null,
        end: '2026-09-20',
        created_at: '2026-08-01',
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

    it('places a due-date-only task on its due date', () => {
        renderCalendar();

        expect(screen.getByTestId('event-dates-due-only')).toHaveTextContent(
            '2026-09-20–2026-09-20',
        );
    });

    it('lets users jump directly to a selected date', () => {
        renderCalendar();

        const picker = screen.getByLabelText('Jump to date');
        expect(picker).toHaveClass('input-date');

        fireEvent.change(picker, {
            target: { value: '2027-04-05' },
        });

        expect(screen.getByTestId('calendar-date')).toHaveTextContent('2027-04-05');
    });

    it('renders the schedule mode selected by its parent', () => {
        render(
            <MemoryRouter>
                <CalendarBoard epics={EPICS} view="agenda" />
            </MemoryRouter>,
        );

        expect(screen.getByTestId('calendar-view')).toHaveTextContent('agenda');
    });
});
