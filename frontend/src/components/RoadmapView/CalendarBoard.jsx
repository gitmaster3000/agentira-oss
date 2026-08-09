import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calendar, dateFnsLocalizer } from 'react-big-calendar';
import { format, parse, parseISO, startOfWeek, getDay } from 'date-fns';
import { enUS } from 'date-fns/locale';
import { ChevronLeft, ChevronRight } from 'lucide-react';
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

function toScheduleDate(value) {
    if (value instanceof Date) return new Date(value);
    return typeof value === 'string' ? parseISO(value) : new Date(value);
}

/**
 * Month / week / agenda detail for the roadmap's unified Schedule view.
 *
 * A task shows on the day(s) it is scheduled for: start → due when both are
 * set, otherwise the single date it has. Tasks with no dates at all are not
 * invented onto the calendar — they're counted in the footer instead, so the
 * gap is visible rather than hidden.
 */
function CalendarToolbar({ label, onNavigate }) {
    return (
        <div className="flex items-center gap-2 mb-3">
            <button
                type="button"
                className="btn btn-ghost px-2"
                onClick={() => onNavigate('PREV')}
                aria-label="Previous period"
            >
                <ChevronLeft className="w-4 h-4" />
            </button>
            <button
                type="button"
                className="btn btn-ghost text-xs"
                onClick={() => onNavigate('TODAY')}
            >
                Today
            </button>
            <button
                type="button"
                className="btn btn-ghost px-2"
                onClick={() => onNavigate('NEXT')}
                aria-label="Next period"
            >
                <ChevronRight className="w-4 h-4" />
            </button>
            <span className="text-sm font-semibold text-text-primary ml-1">{label}</span>
        </div>
    );
}

export function CalendarBoard({
    epics = [],
    milestones = [],
    view = 'month',
    date = new Date(),
    rangeStart = null,
    rangeEnd = null,
    onNavigate = () => {},
}) {
    const navigate = useNavigate();

    const { events, undated } = useMemo(() => {
        const out = [];
        let undated = 0;
        for (const epic of epics) {
            for (const task of epic.tasks || []) {
                const start = task.start ? toScheduleDate(task.start) : null;
                const end = task.end ? toScheduleDate(task.end) : null;
                if (!start && !end) { undated += 1; continue; }
                out.push({
                    id: task.id,
                    kind: 'task',
                    title: `${task.key || task.id} ${task.title}`,
                    start: start || end,
                    end: end || start,
                    allDay: true,
                    resource: { task, epic: epic.name },
                });
            }
        }
        for (const ms of milestones) {
            if (!ms.due_date) continue;
            const day = toScheduleDate(ms.due_date);
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

    const dayStyle = (day) => {
        if (!rangeStart) return {};
        const start = toScheduleDate(rangeStart);
        const end = toScheduleDate(rangeEnd || rangeStart);
        start.setHours(0, 0, 0, 0);
        end.setHours(23, 59, 59, 999);
        return day >= start && day <= end ? { className: 'rbc-selected-range' } : {};
    };

    return (
        <div className="card p-3">
            <div className="rbc-agentira" style={{ height: 620 }}>
                <Calendar
                    localizer={localizer}
                    events={events}
                    view={view}
                    onView={() => {}}
                    date={date}
                    onNavigate={onNavigate}
                    views={['month', 'week', 'day', 'agenda']}
                    components={{ toolbar: CalendarToolbar }}
                    dayPropGetter={dayStyle}
                    popup
                    eventPropGetter={eventStyle}
                    onSelectEvent={(event) => {
                        if (event.kind === 'task') {
                            const task = event.resource.task;
                            navigate(ROUTES.STUDIO_TASK(task.key || task.id));
                        }
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
