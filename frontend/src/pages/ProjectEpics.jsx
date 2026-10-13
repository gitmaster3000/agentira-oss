import React, { useMemo } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { ROUTES } from '../routes';

const STATUS_LABELS = { backlog: 'Backlog', in_progress: 'In progress', done: 'Done' };

// Epics tab: list of the project's epics with progress. Epics come from
// ProjectLayout's outlet context. The epics payload has no done count (only
// task_count), so done is derived from board tasks to avoid an extra fetch.
export function ProjectEpics() {
    const navigate = useNavigate();
    const { epics = [], board } = useOutletContext() || {};
    const doneByEpic = useMemo(() => {
        const counts = {};
        Object.values(board?.columns || {}).flat().forEach(t => {
            if (t.epic_id && t.status === 'done') counts[t.epic_id] = (counts[t.epic_id] || 0) + 1;
        });
        return counts;
    }, [board]);

    return (
        <div className="h-full overflow-auto p-4">
            <div className="flex items-center mb-3">
                <h3 className="text-title-md font-medium">Epics</h3>
                <div className="flex-1" />
                <button
                    type="button"
                    onClick={() => window.dispatchEvent(new CustomEvent('open-create-epic'))}
                    className="flex items-center gap-1.5 border rounded-lg px-3 py-1.5 text-[13px] text-text-secondary hover:text-text-primary transition-colors"
                >
                    <Plus className="w-3.5 h-3.5" /> New epic
                </button>
            </div>
            {epics.length === 0 ? (
                <p className="text-body-sm text-text-secondary">No epics yet. Create one to group related tasks.</p>
            ) : (
                <ul className="flex flex-col gap-2">
                    {epics.map(ep => {
                        const total = ep.task_count || 0;
                        const done = Math.min(doneByEpic[ep.id] || 0, total);
                        const pct = total ? Math.round((done / total) * 100) : 0;
                        return (
                            <li key={ep.id}>
                                <button
                                    type="button"
                                    onClick={() => navigate(ROUTES.STUDIO_EPIC(ep.id))}
                                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border hover:bg-bg-hover text-left transition-colors"
                                >
                                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: ep.color || '#7c4dff' }} />
                                    <span className="flex-1 min-w-0 truncate text-[13.5px] text-text-primary">{ep.title}</span>
                                    <span className="text-[11px] text-text-secondary">{STATUS_LABELS[ep.status] || ep.status}</span>
                                    <span className="text-[12px] text-text-tertiary w-28 truncate">{ep.assignee ? `@${ep.assignee}` : 'Unassigned'}</span>
                                    <span className="flex items-center gap-2 w-40">
                                        <span role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="flex-1 h-1.5 rounded-full bg-bg-app overflow-hidden">
                                            <span className="block h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: ep.color || '#7c4dff' }} />
                                        </span>
                                        <span className="text-[11px] text-text-tertiary tabular-nums">{done}/{total}</span>
                                    </span>
                                </button>
                            </li>
                        );
                    })}
                </ul>
            )}
        </div>
    );
}
