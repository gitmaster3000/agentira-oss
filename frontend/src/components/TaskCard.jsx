import React, { useState, useEffect, useRef, memo } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { Trash2, ChevronDown, Check, ExternalLink, Plus, X } from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { ConfirmModal } from './ConfirmModal';

// Priority pill colors. Hex matches the design tokens
// (tokens/colors.css --priority-*) — these are theme-independent accents.
const PRIORITY = {
    critical: { color: '#f85149', bg: 'rgba(248,81,73,.14)' },
    high:     { color: '#ff9800', bg: 'rgba(255,152,0,.14)' },
    medium:   { color: 'var(--accent-mono-blue)', bg: 'rgba(124,141,181,.14)' },
    low:      { color: 'var(--text-muted)', bg: 'rgba(118,131,144,.14)' },
};

const LAVENDER = 'var(--brand-lavender)';

// Epic chip doubling as a dropdown: reassign the task's epic from the board.
// Optimistic — shows the new epic at once, rolls back if the save fails.
function EpicChip({ task, epics = [], onChanged }) {
    const [open, setOpen] = useState(false);
    const [pos, setPos] = useState(null);
    const [query, setQuery] = useState('');
    const btnRef = useRef(null);
    const menuRef = useRef(null);
    const [override, setOverride] = useState(null);

    // Fresh server data supersedes the optimistic value.
    useEffect(() => { setOverride(null); }, [task.epic_id]);

    const current = override || (task.epic_id ? { id: task.epic_id, name: task.epic_name, color: task.epic_color } : null);
    const color = current?.color || LAVENDER;
    const searchable = epics.length > 5;
    const q = query.trim().toLowerCase();
    const shown = q ? epics.filter(ep => ep.title.toLowerCase().includes(q)) : epics;

    // Menu is portaled to <body> with fixed coords so the column's scroll
    // container can't clip it; flips upward when there's no room below.
    const toggle = (e) => {
        e.stopPropagation();
        if (!open) {
            const r = btnRef.current.getBoundingClientRect();
            const up = window.innerHeight - r.bottom < 340 && r.top > window.innerHeight - r.bottom;
            setPos({ left: r.left, ...(up ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }) });
            setQuery('');
        }
        setOpen(!open);
    };

    useEffect(() => {
        if (!open) return undefined;
        const onDown = (e) => {
            if (!btnRef.current?.contains(e.target) && !menuRef.current?.contains(e.target)) setOpen(false);
        };
        const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
        // Scrolling the epic list itself must not close the menu.
        const onScroll = (e) => { if (!(e.target instanceof Node && menuRef.current?.contains(e.target))) setOpen(false); };
        const close = () => setOpen(false);
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        window.addEventListener('scroll', onScroll, true);
        window.addEventListener('resize', close);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
            window.removeEventListener('scroll', onScroll, true);
            window.removeEventListener('resize', close);
        };
    }, [open]);

    const choose = async (e, epic) => {
        e.stopPropagation();
        setOpen(false);
        if ((epic?.id || null) === (current?.id || null)) return;
        const prev = override;
        setOverride(epic ? { id: epic.id, name: epic.title, color: epic.color } : { id: null });
        try {
            await api.updateTask(task.id, { epic_id: epic ? epic.id : '' });
            if (onChanged) onChanged();
        } catch (err) {
            setOverride(prev);
            alert(err.message);
        }
    };

    const dot = (c) => <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, flexShrink: 0 }} />;
    const footBtn = 'flex-1 flex items-center justify-center gap-1.5 py-2 text-xs transition-colors';

    return (
        <div className="relative min-w-0" onClick={(e) => e.stopPropagation()}>
            <button
                ref={btnRef}
                type="button"
                aria-label="Epic"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={toggle}
                className="flex items-center max-w-full"
                style={current?.name
                    ? { gap: 5, fontSize: 10.5, fontWeight: 600, padding: '2px 7px', borderRadius: 4, background: `${color}22`, color }
                    : { gap: 5, fontSize: 10.5, fontWeight: 600, padding: '1px 6px', borderRadius: 4, border: '1px dashed var(--border-subtle)', color: 'var(--text-muted)' }}
                title={current?.name ? `Epic: ${current.name}` : 'Add to an epic'}
            >
                {current?.name ? dot(color) : <Plus className="w-2.5 h-2.5 flex-shrink-0" />}
                <span className="truncate">{current?.name || 'Add epic'}</span>
                <ChevronDown className="w-2.5 h-2.5 flex-shrink-0" />
            </button>
            {open && pos && createPortal(
                <div
                    ref={menuRef}
                    role="menu"
                    aria-label="Move to epic"
                    className="dropdown-menu"
                    style={{ position: 'fixed', ...pos, width: 280, padding: 0 }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <div className="px-3 pt-2.5 pb-1.5 text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Move to epic</div>
                    {searchable && (
                        <input
                            autoFocus
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Find an epic…"
                            className="mx-2 mb-1.5 px-2 py-1.5 text-xs rounded-md outline-none"
                            style={{ width: 'calc(100% - 16px)', background: 'var(--bg-app)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)' }}
                        />
                    )}
                    <div className="px-1 pb-1" style={{ maxHeight: 240, overflowY: 'auto' }}>
                        {shown.map(ep => {
                            const sel = ep.id === current?.id;
                            return (
                                <button
                                    key={ep.id}
                                    role="menuitemradio"
                                    aria-checked={sel}
                                    type="button"
                                    className="w-full flex items-start gap-2 px-2 py-1.5 rounded-md text-left text-[12.5px] leading-snug hover:bg-[var(--bg-hover)]"
                                    style={{ color: sel ? 'var(--accent-primary)' : 'var(--text-primary)', background: sel ? 'rgba(201,184,255,.08)' : undefined }}
                                    onClick={(e) => choose(e, ep)}
                                >
                                    <span className="mt-1">{dot(ep.color || LAVENDER)}</span>
                                    <span className="flex-1">{ep.title}</span>
                                    {sel && <Check className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" aria-hidden />}
                                </button>
                            );
                        })}
                        {shown.length === 0 && (
                            <div className="px-2 py-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>{epics.length ? 'No epic matches' : 'No epics yet'}</div>
                        )}
                    </div>
                    {current?.id && (
                        <div className="flex" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                            <Link role="menuitem" to={ROUTES.STUDIO_EPIC(current.id)} className={`${footBtn} hover:bg-[var(--bg-hover)]`} style={{ color: 'var(--text-secondary)' }} onClick={() => setOpen(false)}>
                                <ExternalLink className="w-3.5 h-3.5" aria-hidden />Open epic
                            </Link>
                            <button role="menuitem" type="button" title="Remove from epic" className={`${footBtn} hover:text-[var(--danger)] hover:bg-[rgba(248,81,73,.08)]`} style={{ color: 'var(--text-secondary)', borderLeft: '1px solid var(--border-subtle)' }} onClick={(e) => choose(e, null)}>
                                <X className="w-3.5 h-3.5" aria-hidden />Remove
                            </button>
                        </div>
                    )}
                </div>,
                document.body,
            )}
        </div>
    );
}

export const TaskCard = memo(function TaskCard({ task, epics, onUpdate, onDelete, onEpicChange }) {
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

    const handleDragStart = (e) => {
        e.dataTransfer.setData('taskId', task.id);
    };

    const handleDeleteClick = async (e) => {
        e.stopPropagation();
        try {
            await api.deleteTask(task.id);
            if (onDelete) onDelete();
        } catch (err) {
            alert(err.message);
            setIsConfirmingDelete(false);
        }
    };

    const live = task.agent_active;
    const prio = PRIORITY[task.priority] || PRIORITY.medium;
    // No priority color on the left edge — only the live-agent indicator,
    // which appears just for active tasks. Priority still reads via its pill.
    const leftBorder = live ? 'var(--pulse-blue)' : 'var(--border-subtle)';

    return (
        <div
            draggable
            onDragStart={handleDragStart}
            onClick={(e) => { e.stopPropagation(); onUpdate(task); }}
            className={`group relative cursor-pointer ${live ? 'agent-active-glow' : ''}`}
            style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderLeft: `3px solid ${leftBorder}`,
                borderRadius: 6,
                padding: 10,
            }}
            title={live ? 'An agent is working on this task' : undefined}
        >
            {/* Delete (hover only) */}
            <button
                onClick={(e) => { e.stopPropagation(); setIsConfirmingDelete(true); }}
                className="absolute top-1.5 right-1.5 p-1 rounded-sm opacity-0 group-hover:opacity-100 transition-opacity z-10"
                style={{ color: 'var(--text-tertiary)', backgroundColor: 'var(--bg-panel)' }}
                title="Delete task"
            >
                <Trash2 className="w-3.5 h-3.5" />
            </button>

            {isConfirmingDelete && (
                <ConfirmModal
                    title="Delete Task"
                    message={`Are you sure you want to delete task "${task.title}"?`}
                    confirmText="Delete"
                    onConfirm={handleDeleteClick}
                    onCancel={(e) => { e?.stopPropagation(); setIsConfirmingDelete(false); }}
                />
            )}

            {/* Key + live / needs-attention */}
            <div className="flex items-center justify-between" style={{ marginBottom: 5 }}>
                <span style={{ fontSize: 10.5, fontFamily: 'ui-monospace,monospace', color: 'var(--accent-mono-blue)' }}>
                    {task.key || task.id}
                </span>
                {live ? (
                    <span className="flex items-center" style={{ gap: 4 }}>
                        <span style={{ width: 13, height: 13, borderRadius: 4, background: 'rgba(0,188,212,.16)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="#00bcd4" strokeWidth="2.6"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle></svg>
                        </span>
                        <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--pulse-blue)' }}>LIVE</span>
                    </span>
                ) : task.needs_attention ? (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ff9800" strokeWidth="2" title="Needs attention"><path d="M12 9v4M12 17h.01"></path><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path></svg>
                ) : null}
            </div>

            {/* Title */}
            <div style={{ fontSize: 12, lineHeight: 1.35, marginBottom: 9, color: 'var(--text-primary)' }} className="line-clamp-2 pr-5">
                {task.title}
            </div>

            {/* Epic + priority · assignee */}
            <div className="flex items-center justify-between">
                <div className="flex items-center min-w-0" style={{ gap: 5 }}>
                    <EpicChip task={task} epics={epics} onChanged={onEpicChange} />
                    {task.priority && (
                        <span className="flex-shrink-0" style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 3, textTransform: 'capitalize', background: prio.bg, color: prio.color }}>
                            {task.priority}
                        </span>
                    )}
                </div>
                {task.assignee && (
                    <span
                        style={{ width: 20, height: 20, borderRadius: '50%', background: 'var(--bg-panel)', color: 'var(--text-secondary)', fontSize: 9, fontWeight: 700 }}
                        className="flex items-center justify-center flex-shrink-0"
                        title={task.assignee}
                    >
                        {task.assignee.slice(0, 2).toUpperCase()}
                    </span>
                )}
            </div>
        </div>
    );
});
