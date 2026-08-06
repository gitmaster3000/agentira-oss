import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calendar, dateFnsLocalizer } from 'react-big-calendar';
import { format, parse, startOfWeek, getDay } from 'date-fns';
import { enUS } from 'date-fns/locale';
import 'react-big-calendar/lib/css/react-big-calendar.css';
import './calendar-theme.css';
import { ROUTES } from '../../routes';

const localizer = dateFnsLocalizer({
    format, parse, startOfWeek, getDay, locales: { 'en-US': enUS },
});

const STATUS_COLORS = {
    done: '#2ecc71',
    review: '#ff9800',
    in_progress: '#7c4dff',
    todo: '#00bcd4',
    backlog: '#5f6368',
};

/**
 * Month / week / agenda calendar over the roadmap.
 *
 * A task shows on the day(s) it is scheduled for: start → due when both are
 * set, otherwise the single date it has. Tasks with no dates at all are not
 * invented onto the calendar — they're counted in the footer instead, so the
 * gap is visible rather than hidden.
 */
export function CalendarBoard({ epics = [], milestones = [] }) {
    const navigate = useNavigate();
    const [view, setView] = useState('month');
    const [date, setDate] = useState(new Date());

    const { events, undated } = useMemo(() => {
        const out = [];
        let undated = 0;
        for (const epic of epics) {
            for (const task of epic.tasks || []) {
                const start = task.start ? new Date(task.start) : null;
                const end = task.end ? new Date(task.end) : null;
                if (!start && !end) { undated += 1; continue; }
                out.push({
                    id: task.id,
                    kind: 'task',
                    title: `${task.key} ${task.title}`,
                    start: start || end,
                    end: end || start,
                    allDay: true,
                    resource: { task, epic: epic.name },
                });
            }
        }
        for (const ms of milestones) {
            if (!ms.due_date) continue;
            const day = new Date(ms.due_date);
            out.push({
                id: `ms-${ms.id}`,
                kind: 'milestone',
                title: `🚩 ${ms.title} (${ms.done}/${ms.total})`,
                start: day,
                end: day,
                allDay: true,
                resource: { milestone: ms },
            });
        }
        return { events: out, undated };
    }, [epics, milestones]);

    const eventStyle = (event) => {
        if (event.kind === 'milestone') {
            const color = event.resource.milestone.color || '#2ecc71';
            return { style: { backgroundColor: 'transparent', color, border: `1px solid ${color}`, fontWeight: 600 } };
        }
        const task = event.resource.task;
        const color = STATUS_COLORS[task.status] || STATUS_COLORS.backlog;
        return {
            style: {
                backgroundColor: color,
                opacity: task.status === 'done' ? 0.55 : 1,
                border: task.is_blocked ? '1px dashed #e74c3c' : 'none',
            },
        };
    };

    return (
        <div className="card p-3">
            <div className="rbc-agentira" style={{ height: 620 }}>
                <Calendar
                    localizer={localizer}
                    events={events}
                    view={view}
                    onView={setView}
                    date={date}
                    onNavigate={setDate}
                    views={['month', 'week', 'agenda']}
                    popup
                    eventPropGetter={eventStyle}
                    onSelectEvent={(event) => {
                        if (event.kind === 'task') navigate(ROUTES.STUDIO_TASK(event.id));
                    }}
                    startAccessor="start"
                    endAccessor="end"
                />
            </div>
            {undated > 0 && (
                <p className="text-xs text-text-tertiary mt-3">
                    {undated} {undated === 1 ? 'task has' : 'tasks have'} no dates yet, so they don't
                    appear here. Set a start or due date on a task to schedule it.
                </p>
            )}
        </div>
    );
}
