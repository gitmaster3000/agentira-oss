import React, { useEffect, useRef, useState } from 'react';
import { Search, ChevronDown, SlidersHorizontal, Star, Layers, Rows3, AlignJustify, Settings2, Plus, Check, X } from 'lucide-react';
import { UserAvatar } from './UserAvatar';

const PRIORITIES = [
    { value: 'critical', label: 'Critical', color: '#f85149' },
    { value: 'high', label: 'High', color: '#ff9800' },
    { value: 'medium', label: 'Medium', color: '#facc15' },
    { value: 'low', label: 'Low', color: '#38bdf8' },
];
const MAX_AVATARS = 4;

const btnBase = 'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12.5px] whitespace-nowrap transition-colors bg-bg-app';
const btnIdle = 'text-text-secondary hover:border-border-active hover:text-text-primary';
const btnActive = 'border-accent-primary text-text-primary';

function usePopover() {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open]);
    return { open, setOpen, ref };
}

function Row({ on, onClick, children }) {
    return (
        <button type="button" onClick={onClick} className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg text-[12.5px] text-text-primary hover:bg-bg-hover text-left">
            <span className={`w-[15px] h-[15px] rounded border flex items-center justify-center shrink-0 ${on ? 'bg-accent-primary border-accent-primary' : 'border-border-active'}`}>
                {on && <Check className="w-2.5 h-2.5 text-black" strokeWidth={3} />}
            </span>
            {children}
        </button>
    );
}

const Heading = ({ children }) => (
    <div className="px-2 pt-1.5 pb-1 text-[9.5px] font-bold uppercase tracking-wider text-text-tertiary">{children}</div>
);

const storageKey = (projectId) => `agentira.boardFilters.${projectId}`;
function loadSaved(projectId) {
    try { return JSON.parse(localStorage.getItem(storageKey(projectId))) || []; } catch { return []; }
}

export function BoardToolbar({
    projectId, members, epics,
    searchQuery, setSearchQuery,
    filterPriority, setFilterPriority,
    filterAssignee, setFilterAssignee,
    filterEpic, setFilterEpic,
    onCreate,
}) {
    const searchRef = useRef(null);
    const epicPop = usePopover();
    const filterPop = usePopover();
    const savedPop = usePopover();
    const [saved, setSaved] = useState(() => loadSaved(projectId));
    const [saveName, setSaveName] = useState('');

    useEffect(() => { setSaved(loadSaved(projectId)); }, [projectId]);

    // "/" focuses search unless the user is already typing somewhere.
    useEffect(() => {
        const onKey = (e) => {
            if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
            const el = document.activeElement;
            if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
            e.preventDefault();
            searchRef.current?.focus();
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, []);

    const filterCount = (filterPriority ? 1 : 0) + (filterAssignee ? 1 : 0);
    const anyActive = !!(searchQuery || filterPriority || filterAssignee || filterEpic);
    const clearAll = () => { setSearchQuery(''); setFilterPriority(''); setFilterAssignee(''); setFilterEpic(''); };
    const epicLabel = epics.find(ep => String(ep.id) === String(filterEpic))?.title;

    const persist = (next) => {
        setSaved(next);
        try { localStorage.setItem(storageKey(projectId), JSON.stringify(next)); } catch { /* storage unavailable */ }
    };
    const saveCurrent = () => {
        const name = saveName.trim();
        if (!name) return;
        persist([...saved.filter(s => s.name !== name), { name, priority: filterPriority, assignee: filterAssignee, epic: filterEpic }]);
        setSaveName('');
    };
    const applySaved = (s) => {
        setFilterPriority(s.priority || ''); setFilterAssignee(s.assignee || ''); setFilterEpic(s.epic || '');
        savedPop.setOpen(false);
    };

    const shown = members.slice(0, MAX_AVATARS);
    const extra = members.length - shown.length;
    const popClass = 'dropdown-menu top-full left-0 mt-1.5 p-1.5';
    const soon = 'Coming soon';

    return (
        <header className="px-4 py-2.5 flex items-center gap-2 flex-wrap shrink-0 border-b">
            <div className="relative group">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary group-focus-within:text-accent-primary transition-colors" />
                <input
                    ref={searchRef} type="text" placeholder="Search board" aria-label="Search board"
                    className="bg-bg-app border rounded-lg pl-8 pr-8 py-1.5 text-[13px] w-40 focus:w-56 focus:outline-none focus:border-accent-primary transition-all text-text-primary"
                    value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                />
                <kbd className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] leading-4 px-1 rounded border text-text-tertiary pointer-events-none">/</kbd>
            </div>

            <div className="flex items-center pl-1.5" role="group" aria-label="Filter by assignee">
                {shown.map(m => {
                    const on = filterAssignee === m.name;
                    return (
                        <button
                            key={m.id} type="button" title={m.display_name || m.name} aria-pressed={on}
                            onClick={() => setFilterAssignee(on ? '' : m.name)}
                            className={`-ml-1.5 rounded-full border-2 hover:-translate-y-0.5 transition-transform ${on ? 'ring-2 ring-accent-primary relative z-10' : ''}`}
                            style={{ borderColor: 'var(--bg-app)' }}
                        >
                            <UserAvatar profile={m} size={24} />
                        </button>
                    );
                })}
                {extra > 0 && (
                    <span className="-ml-1.5 w-[28px] h-[28px] rounded-full bg-bg-hover text-text-secondary text-[10px] font-bold flex items-center justify-center border-2" style={{ borderColor: 'var(--bg-app)' }} title={`${extra} more`}>+{extra}</span>
                )}
            </div>

            <span className="w-px h-5 bg-border-subtle mx-1" />

            <div className="relative" ref={epicPop.ref}>
                <button type="button" onClick={() => epicPop.setOpen(o => !o)} className={`${btnBase} ${filterEpic ? btnActive : btnIdle}`}>
                    <span className="w-[9px] h-[9px] rounded-[3px] bg-accent-primary" />
                    <span className="max-w-[140px] truncate">{epicLabel || 'Epic'}</span>
                    <ChevronDown className="w-3 h-3" />
                </button>
                {epicPop.open && (
                    <div className={popClass} style={{ minWidth: 220, maxHeight: 320, overflowY: 'auto' }}>
                        <Heading>Epic</Heading>
                        <Row on={!filterEpic} onClick={() => { setFilterEpic(''); epicPop.setOpen(false); }}>All epics</Row>
                        {epics.map(ep => (
                            <Row key={ep.id} on={String(filterEpic) === String(ep.id)} onClick={() => { setFilterEpic(ep.id); epicPop.setOpen(false); }}>
                                <span className="truncate">{ep.title}</span>
                            </Row>
                        ))}
                    </div>
                )}
            </div>

            <div className="relative" ref={filterPop.ref}>
                <button type="button" onClick={() => filterPop.setOpen(o => !o)} className={`${btnBase} ${filterCount ? btnActive : btnIdle}`}>
                    <SlidersHorizontal className="w-3.5 h-3.5" /> Filter
                    {filterCount > 0 && <span className="bg-accent-primary text-black rounded-full text-[10px] font-bold px-1.5 leading-4">{filterCount}</span>}
                </button>
                {filterPop.open && (
                    <div className={popClass} style={{ width: 'min(420px, 90vw)' }}>
                        <div className="grid grid-cols-2 gap-1">
                            <div>
                                <Heading>Priority</Heading>
                                {PRIORITIES.map(p => (
                                    <Row key={p.value} on={filterPriority === p.value} onClick={() => setFilterPriority(filterPriority === p.value ? '' : p.value)}>
                                        <span className="w-2 h-2 rounded-full" style={{ background: p.color }} />{p.label}
                                    </Row>
                                ))}
                            </div>
                            <div style={{ maxHeight: 260, overflowY: 'auto' }}>
                                <Heading>Assignee</Heading>
                                {members.map(m => (
                                    <Row key={m.id} on={filterAssignee === m.name} onClick={() => setFilterAssignee(filterAssignee === m.name ? '' : m.name)}>
                                        <UserAvatar profile={m} size={18} /><span className="truncate">{m.display_name || m.name}</span>
                                    </Row>
                                ))}
                            </div>
                        </div>
                        <div className="flex items-center justify-between gap-2 border-t border-border-subtle mt-1.5 pt-2 px-1">
                            <div className="flex items-center gap-1.5 min-w-0">
                                <input
                                    value={saveName} onChange={e => setSaveName(e.target.value)} placeholder="Name this filter" aria-label="Name this filter"
                                    onKeyDown={e => { if (e.key === 'Enter') saveCurrent(); }}
                                    className="input" style={{ padding: '4px 8px', fontSize: 12, width: 130 }}
                                />
                                <button type="button" onClick={saveCurrent} disabled={!saveName.trim() || !(filterCount || filterEpic)} className={`${btnBase} ${btnIdle} disabled:opacity-40`}>Save</button>
                            </div>
                            <button type="button" onClick={clearAll} className="text-[11.5px] text-accent-primary hover:underline">Clear all</button>
                        </div>
                    </div>
                )}
            </div>

            <div className="relative" ref={savedPop.ref}>
                <button type="button" onClick={() => savedPop.setOpen(o => !o)} className={`${btnBase} ${btnIdle}`}>
                    <Star className="w-3.5 h-3.5" /> Custom filters
                </button>
                {savedPop.open && (
                    <div className={popClass} style={{ minWidth: 220 }}>
                        <Heading>Saved</Heading>
                        {saved.length === 0 && <div className="px-2 py-2 text-text-tertiary text-[12px]">No saved filters yet. Set filters, then name and save them from the Filter menu.</div>}
                        {saved.map(s => (
                            <div key={s.name} className="group flex items-center rounded-lg hover:bg-bg-hover">
                                <button type="button" onClick={() => applySaved(s)} className="flex-1 flex items-center gap-2 px-2 py-1.5 text-[12.5px] text-text-primary text-left min-w-0">
                                    <Star className="w-3 h-3 shrink-0" /><span className="truncate">{s.name}</span>
                                </button>
                                <button type="button" title="Delete" aria-label={`Delete ${s.name}`} onClick={() => persist(saved.filter(x => x.name !== s.name))} className="px-2 opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400">
                                    <X className="w-3.5 h-3.5" />
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {anyActive && (
                <button type="button" onClick={clearAll} className={`${btnBase} border-transparent bg-transparent text-text-secondary hover:text-text-primary`}>Clear filters</button>
            )}

            <button type="button" disabled title={soon} className={`${btnBase} ${btnIdle} opacity-50 cursor-not-allowed`}>
                <Layers className="w-3.5 h-3.5" /> Group <ChevronDown className="w-3 h-3" />
            </button>

            <div className="flex-1" />

            <div className="inline-flex rounded-lg border overflow-hidden opacity-50" title={`Card density — ${soon}`}>
                <button type="button" disabled aria-label="Comfortable" className="px-2 py-1.5 bg-bg-hover text-text-primary cursor-not-allowed"><Rows3 className="w-3.5 h-3.5" /></button>
                <button type="button" disabled aria-label="Compact" className="px-2 py-1.5 text-text-tertiary cursor-not-allowed"><AlignJustify className="w-3.5 h-3.5" /></button>
            </div>
            <button type="button" disabled title={`Show / hide columns — ${soon}`} className={`${btnBase} ${btnIdle} opacity-50 cursor-not-allowed`}>
                <Settings2 className="w-3.5 h-3.5" /> View
            </button>
            <button type="button" onClick={onCreate} className={`${btnBase} border-transparent bg-accent-primary text-black font-semibold hover:brightness-110`} style={{ background: 'var(--accent-primary)' }}>
                <Plus className="w-3.5 h-3.5" /> New task
            </button>
        </header>
    );
}
