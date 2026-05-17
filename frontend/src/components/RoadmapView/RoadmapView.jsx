import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CalendarDays, CheckCircle, Clock, Circle, ChevronDown, ChevronRight, Flag, Target, ExternalLink } from 'lucide-react';
import { api } from '../../api';
import { ROUTES } from '../../routes';

const STATUS_COLORS = {
    done: '#2ecc71',
    review: '#ff9800',
    in_progress: '#7c4dff',
    todo: '#00bcd4',
    backlog: '#5f6368',
};

const PRIORITY_DOTS = {
    critical: '#e74c3c',
    high: '#ff9800',
    medium: '#f1c40f',
    low: '#5f6368',
};

function EpicProgress({ epic }) {
    const pct = epic.progress;
    return (
        <div className="flex items-center gap-3 min-w-0">
            <div className="flex-1 h-1.5 rounded-full bg-bg-tertiary overflow-hidden max-w-[120px]">
                <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${pct}%`, backgroundColor: pct === 100 ? STATUS_COLORS.done : STATUS_COLORS.in_progress }}
                />
            </div>
            <span className="text-xs text-text-tertiary whitespace-nowrap">{epic.done}/{epic.total}</span>
        </div>
    );
}

function TaskRow({ task }) {
    const statusColor = STATUS_COLORS[task.status] || STATUS_COLORS.backlog;
    const priorityColor = PRIORITY_DOTS[task.priority] || PRIORITY_DOTS.medium;
    const Icon = task.progress === 100 ? CheckCircle : task.progress > 0 ? Clock : Circle;

    return (
        <div className="flex items-center gap-3 px-4 py-2 hover:bg-bg-hover rounded-md transition-colors group">
            <Icon className="w-3.5 h-3.5 flex-shrink-0" style={{ color: statusColor }} />
            <div
                className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: priorityColor }}
                title={task.priority}
            />
            <span className="text-[10px] font-mono text-text-tertiary flex-shrink-0">{task.key || task.id}</span>
            <span className="text-sm text-text-primary flex-1 min-w-0 truncate">{task.title}</span>
            {task.assignee && (
                <span className="text-xs text-text-tertiary px-1.5 py-0.5 rounded bg-bg-tertiary hidden group-hover:inline">
                    {task.assignee}
                </span>
            )}
            <span
                className="text-xs px-1.5 py-0.5 rounded font-medium text-white"
                style={{ backgroundColor: statusColor }}
            >
                {task.status.replace('_', ' ')}
            </span>
            {task.end && (
                <span className="text-xs text-text-tertiary whitespace-nowrap">
                    {formatDate(task.end)}
                </span>
            )}
        </div>
    );
}

function EpicSection({ epic }) {
    const navigate = useNavigate();
    const [open, setOpen] = useState(epic.in_progress > 0 || epic.progress < 100);
    const Arrow = open ? ChevronDown : ChevronRight;
    const epicId = epic.id || epic.epic_id;

    return (
        <div className="card p-0 overflow-hidden">
            {/* Header row: chevron toggles expand inline; clicking the
                epic title navigates to the dedicated epic page. Two
                independent click targets, no nested-button. */}
            <div className="flex items-center gap-3 px-4 py-3 hover:bg-bg-hover transition-colors">
                <button
                    onClick={() => setOpen(!open)}
                    className="text-text-tertiary hover:text-text-primary"
                    title={open ? 'Collapse' : 'Expand'}
                >
                    <Arrow className="w-4 h-4 flex-shrink-0" />
                </button>
                <Target
                    className="w-4 h-4 flex-shrink-0"
                    style={{ color: epic.color || 'var(--accent-primary)' }}
                />
                <button
                    onClick={() => epicId && navigate(ROUTES.STUDIO_EPIC(epicId))}
                    disabled={!epicId}
                    className="text-sm font-semibold text-text-primary flex-1 text-left hover:underline disabled:no-underline disabled:cursor-default"
                    title={epicId ? 'Open epic' : ''}
                >
                    {epic.name}
                </button>
                {epicId && (
                    <button
                        onClick={() => navigate(ROUTES.STUDIO_EPIC(epicId))}
                        className="text-text-tertiary hover:text-text-primary"
                        title="Open epic page"
                    >
                        <ExternalLink className="w-3.5 h-3.5" />
                    </button>
                )}
                <EpicProgress epic={epic} />
            </div>
            {open && (
                <div className="border-t border-border-subtle pb-1">
                    {epic.tasks.map((task) => (
                        <TaskRow key={task.id} task={task} />
                    ))}
                </div>
            )}
        </div>
    );
}

function MilestoneTimeline({ milestones }) {
    if (!milestones.length) return null;
    return (
        <div className="card">
            <h3 className="text-sm font-semibold text-text-primary mb-3 flex items-center gap-2">
                <Flag className="w-4 h-4 text-green-400" />
                Recent Milestones
            </h3>
            <div className="relative border-l-2 border-green-500/30 ml-2 pl-4 space-y-3">
                {milestones.map((m) => (
                    <div key={m.id} className="relative">
                        <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-green-500" />
                        <div className="text-sm text-text-primary">{m.title}</div>
                        <div className="text-xs text-text-tertiary">
                            {formatDate(m.date)} · {m.epic}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

function SummaryBar({ summary, groupBy }) {
    const pct = summary.total_tasks > 0 ? Math.round((summary.total_done / summary.total_tasks) * 100) : 0;
    return (
        <div className="flex items-center gap-6 text-sm">
            <div>
                <span className="text-2xl font-bold text-text-primary">{pct}%</span>
                <span className="text-text-tertiary ml-1">complete</span>
            </div>
            <div className="flex-1 h-2 rounded-full bg-bg-tertiary overflow-hidden max-w-xs">
                <div className="h-full rounded-full bg-green-500 transition-all" style={{ width: `${pct}%` }} />
            </div>
            <div className="flex gap-4 text-xs text-text-tertiary">
                <span>{summary.total_tasks} tasks</span>
                <span>{summary.total_epics} {groupBy === 'tag' ? 'tags' : 'epics'}</span>
                <span>{summary.total_done} done</span>
            </div>
        </div>
    );
}

function formatDate(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * Horizontal time-axis showing each epic as a bar from min(task.start) to
 * max(task.end). Tasks without dates are silently skipped — if nothing in
 * the project has dates, we render a friendly "no scheduled work" state
 * instead of an empty grid.
 */
function TimelineStrip({ epics }) {
    // Collect all date-bearing tasks
    const items = [];
    for (const epic of epics || []) {
        const dates = (epic.tasks || [])
            .map(t => ({ start: t.start || t.start_date, end: t.end || t.due_date || t.start || t.start_date }))
            .filter(d => d.start || d.end);
        if (dates.length === 0) continue;
        const earliest = dates.map(d => new Date(d.start || d.end)).reduce((a, b) => a < b ? a : b);
        const latest   = dates.map(d => new Date(d.end || d.start)).reduce((a, b) => a > b ? a : b);
        items.push({
            name: epic.name,
            color: epic.color || '#7c4dff',
            progress: epic.progress || 0,
            taskCount: dates.length,
            start: earliest,
            end: latest,
        });
    }

    if (items.length === 0) {
        return (
            <div className="card p-4 text-sm text-text-tertiary">
                <div className="flex items-center gap-2">
                    <CalendarDays className="w-4 h-4" />
                    <span>No scheduled work yet — set <strong>start / due dates</strong> on tasks to see the timeline.</span>
                </div>
            </div>
        );
    }

    // Pad axis: 1 week before earliest, 1 week after latest
    const axisStart = new Date(Math.min(...items.map(i => i.start.getTime())) - 7 * 86400000);
    const axisEnd   = new Date(Math.max(...items.map(i => i.end.getTime()))   + 7 * 86400000);
    const span = axisEnd - axisStart;

    // Month tick positions across the axis
    const ticks = [];
    let cursor = new Date(axisStart.getFullYear(), axisStart.getMonth(), 1);
    while (cursor <= axisEnd) {
        ticks.push(new Date(cursor));
        cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
    }

    const pct = (d) => `${((d.getTime() - axisStart.getTime()) / span) * 100}%`;
    const widthPct = (a, b) => `${Math.max(2, ((b.getTime() - a.getTime()) / span) * 100)}%`;
    const today = new Date();
    const showToday = today >= axisStart && today <= axisEnd;

    return (
        <div className="card p-0 overflow-hidden">
            <div className="px-4 py-3 border-b border-border-subtle/40 flex items-center gap-2">
                <CalendarDays className="w-4 h-4 text-text-tertiary" />
                <span className="text-xs font-medium text-text-primary uppercase tracking-wider">Timeline</span>
                <span className="text-xs text-text-tertiary ml-auto">
                    {axisStart.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}
                    {' → '}
                    {axisEnd.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}
                </span>
            </div>

            <div className="relative px-4 py-4">
                {/* Month grid + labels */}
                <div className="relative h-5 mb-3">
                    {ticks.map((t, i) => (
                        <div
                            key={i}
                            className="absolute top-0 bottom-0 border-l border-border-subtle/50"
                            style={{ left: pct(t) }}
                        >
                            <span className="absolute -top-0.5 left-1 text-[10px] uppercase tracking-wider text-text-tertiary whitespace-nowrap">
                                {t.toLocaleDateString(undefined, { month: 'short', year: t.getMonth() === 0 ? 'numeric' : undefined })}
                            </span>
                        </div>
                    ))}
                </div>

                {/* Today marker — full-height vertical line behind the bars */}
                {showToday && (
                    <div
                        className="absolute top-9 bottom-2 border-l-2 border-red-500/70 z-10 pointer-events-none"
                        style={{ left: `calc(1rem + ${pct(today)})` }}
                        title={`Today: ${today.toLocaleDateString()}`}
                    >
                        <span className="absolute -top-3 -translate-x-1/2 text-[9px] font-semibold text-red-500 bg-bg-panel px-1 rounded">today</span>
                    </div>
                )}

                {/* One bar per epic */}
                <div className="space-y-2">
                    {items.map((item) => (
                        <div key={item.name} className="relative h-7 flex items-center group">
                            {/* Background row */}
                            <div className="absolute inset-y-0 left-0 right-0 border-t border-border-subtle/20" />
                            {/* The bar */}
                            <div
                                className="absolute h-5 rounded-md flex items-center justify-between px-2 text-[10px] font-medium text-white whitespace-nowrap overflow-hidden"
                                style={{
                                    left: pct(item.start),
                                    width: widthPct(item.start, item.end),
                                    backgroundColor: item.color,
                                }}
                                title={`${item.name} · ${item.start.toLocaleDateString()} → ${item.end.toLocaleDateString()} · ${item.progress}%`}
                            >
                                <span className="truncate">{item.name}</span>
                                <span className="opacity-75 ml-2 flex-shrink-0">{item.progress}%</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

export function RoadmapView({ projectId: projectIdProp }) {
    const { projectId: projectIdParam } = useParams();
    const projectId = projectIdProp || projectIdParam;
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [groupBy, setGroupBy] = useState('epic');

    const loadRoadmap = useCallback(() => {
        if (!projectId) return;
        setLoading(true);
        api.getRoadmap(projectId, groupBy)
            .then(d => {
                setData(d);
                // Seed initial activity ID
                api.getProjectActivity(projectId, 1).then(acts => {
                    if (acts[0]) lastActivityIdRef.current = acts[0].id;
                });
            })
            .catch((err) => {
                console.error('Failed to fetch roadmap:', err);
                setError('Failed to load roadmap.');
            })
            .finally(() => setLoading(false));
    }, [projectId, groupBy]);

    useEffect(() => {
        loadRoadmap();
    }, [loadRoadmap]);

    const lastActivityIdRef = React.useRef(null);
    const checkForUpdates = useCallback(async () => {
        if (document.visibilityState !== 'visible' || !projectId) return;
        try {
            const activities = await api.getProjectActivity(projectId, 1);
            const latest = activities[0];
            if (latest && latest.id !== lastActivityIdRef.current) {
                lastActivityIdRef.current = latest.id;
                api.getRoadmap(projectId, groupBy).then(setData);
            }
        } catch (err) {
            console.error('[Roadmap] checkForUpdates error:', err);
        }
    }, [projectId, groupBy]);

    const checkRef = React.useRef(checkForUpdates);
    useEffect(() => { checkRef.current = checkForUpdates; }, [checkForUpdates]);

    useEffect(() => {
        if (!projectId) return;
        const interval = setInterval(() => checkRef.current(), 30000); // Stable 30s
        return () => clearInterval(interval);
    }, [projectId]);

    if (loading && !data) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary p-6">Loading roadmap...</div>;
    }

    if (error) {
        return <div className="flex-1 flex items-center justify-center text-red-400 p-6">{error}</div>;
    }

    if (!data || !data.summary || !data.epics || data.summary.total_tasks === 0) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center text-text-tertiary p-6">
                <CalendarDays className="w-12 h-12 mb-3 opacity-50" />
                <p className="text-lg font-medium text-text-primary">No roadmap data yet</p>
                <p className="text-sm mt-1">Add tasks with tags to create epics. Set start/due dates for timeline planning.</p>
            </div>
        );
    }

    return (
        <div className="flex-1 p-6 overflow-y-auto space-y-5 h-full max-h-[calc(100vh-64px)]">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
                    <CalendarDays className="w-5 h-5 text-text-tertiary" />
                    Roadmap — {data?.project?.name}
                </h2>
                <div className="flex bg-bg-panel p-1 rounded-lg border border-border-subtle">
                    <button
                        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${groupBy === 'tag' ? 'bg-bg-app text-text-primary shadow-sm' : 'text-text-tertiary hover:text-text-primary'}`}
                        onClick={() => setGroupBy('tag')}
                    >
                        By Tag
                    </button>
                    <button
                        className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${groupBy === 'epic' ? 'bg-bg-app text-text-primary shadow-sm' : 'text-text-tertiary hover:text-text-primary'}`}
                        onClick={() => setGroupBy('epic')}
                    >
                        By Epic
                    </button>
                </div>
            </div>

            {/* Timeline strip — actual horizontal time axis with epic bars
                spanning min(task.start) → max(task.end) per epic. Shows
                "no scheduled work yet" if nothing has dates. */}
            <TimelineStrip epics={data.epics} />

            {/* Summary */}
            <SummaryBar summary={data.summary} groupBy={groupBy} />

            {/* Layout: Epics + Milestones */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                <div className="lg:col-span-2 space-y-3">
                    {data.epics.map((epic) => (
                        <EpicSection key={epic.name} epic={epic} />
                    ))}
                </div>
                <div>
                    <MilestoneTimeline milestones={data.milestones} />
                </div>
            </div>
        </div>
    );
}
