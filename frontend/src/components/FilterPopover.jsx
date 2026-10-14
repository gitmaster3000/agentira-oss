import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, SlidersHorizontal } from 'lucide-react';
import { UNASSIGNED, activeFilterCount } from '../lib/taskFilters';

const PRIORITIES = ['critical', 'high', 'medium', 'low'];
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function toggled(set, value) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value); else next.add(value);
    return next;
}

function Column({ title, options, selected, onToggle }) {
    return (
        <div className="min-w-[150px] max-h-64 overflow-y-auto">
            <div className="px-2 pt-1.5 pb-1 text-[9.5px] font-bold uppercase tracking-wider text-text-tertiary">{title}</div>
            {options.length === 0 && <div className="px-2 py-1.5 text-text-tertiary" style={{ fontSize: 12 }}>None</div>}
            {options.map(o => (
                <label key={o.value} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-bg-hover cursor-pointer" style={{ fontSize: 12.5 }}>
                    <input type="checkbox" checked={selected.has(o.value)} onChange={() => onToggle(o.value)} />
                    <span className="flex-1 truncate text-text-primary">{o.label}</span>
                    <span className="text-text-tertiary" style={{ fontSize: 10.5 }}>{o.count}</span>
                </label>
            ))}
        </div>
    );
}

export function FilterPopover({ filters, counts, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const active = activeFilterCount(filters);

    useEffect(() => {
        function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const set = (key, value) => onChange({ ...filters, [key]: toggled(filters[key], value) });
    const assigneeOptions = Object.keys(counts.assignee)
        .sort((a, b) => (a === UNASSIGNED) - (b === UNASSIGNED) || a.localeCompare(b))
        .map(v => ({ value: v, label: v === UNASSIGNED ? 'Unassigned' : v, count: counts.assignee[v] }));
    const labelOptions = Object.keys(counts.label).sort()
        .map(v => ({ value: v, label: v, count: counts.label[v] }));

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen(v => !v)}
                aria-expanded={open}
                className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-label-lg transition-colors bg-bg-app ${
                    active ? 'border-accent-primary text-text-primary' : 'text-text-secondary hover:border-border-active hover:text-text-primary'
                }`}
            >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                <span>Filter</span>
                {active > 0 && (
                    <span data-testid="filter-badge" style={{ fontSize: 10, fontWeight: 700 }} className="text-text-primary bg-bg-hover rounded-full px-2 py-0.5">{active}</span>
                )}
                <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>
            {open && (
                <div className="dropdown-menu top-full right-0 mt-1.5 p-1.5 flex flex-wrap gap-2" style={{ zIndex: 50, maxWidth: 'calc(100vw - 24px)' }}>
                    <Column title="Priority" selected={filters.priorities} onToggle={v => set('priorities', v)}
                        options={PRIORITIES.map(p => ({ value: p, label: cap(p), count: counts.priority[p] || 0 }))} />
                    <Column title="Assignee" selected={filters.assignees} onToggle={v => set('assignees', v)} options={assigneeOptions} />
                    <Column title="Label" selected={filters.labels} onToggle={v => set('labels', v)} options={labelOptions} />
                </div>
            )}
        </div>
    );
}
