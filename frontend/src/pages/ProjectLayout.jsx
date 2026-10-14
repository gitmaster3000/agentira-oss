import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, useSearchParams, Outlet, useLocation, useNavigate, NavLink, Link } from 'react-router-dom';
import { api } from '../api';
import { TaskDetailPanel } from '../components/TaskDetailPanel';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { ConfirmModal } from '../components/ConfirmModal';
import { X, ChevronDown, Users, Plus } from 'lucide-react';
import { CreateEpicModal } from '../components/CreateEpicModal';
import { ROUTES } from '../routes';
import { setCurrentProjectId } from '../currentProject';
import { UserAvatar } from '../components/UserAvatar';
import { BoardToolbar } from '../components/BoardToolbar';

// Members control — design board-toolbar "Members [N] ▾" dropdown: lists
// current members (remove on hover) + the addable profiles under "Add member".
function MembersControl({ members, availableProfiles, onAdd, onRemove }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const ref = useRef(null);
    useEffect(() => { if (!open) setQuery(''); }, [open]);
    // Nobody is listed until the user starts typing; then only matches show.
    const q = query.trim().toLowerCase();
    const matches = q
        ? availableProfiles.filter(p => [p.name, p.display_name, p.role]
            .some(v => (v || '').toLowerCase().includes(q))).slice(0, 8)
        : [];
    useEffect(() => {
        function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);
    const avatar = (profile) => <UserAvatar profile={profile} size={28} />;
    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen(o => !o)}
                className="flex items-center gap-2 border rounded-lg text-text-secondary hover:text-text-primary transition-colors"
                style={{ padding: '6px 11px', fontSize: 12.5 }}
            >
                <Users className="w-4 h-4" /> Members
                <span style={{ fontSize: 10, fontWeight: 700 }} className="text-text-tertiary bg-bg-app rounded-full px-2 py-0.5">{members.length}</span>
                <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>
            {open && (
                <div className="dropdown-menu top-full left-0 mt-1.5 p-1.5" style={{ width: 268, zIndex: 50 }}>
                    <div className="px-2 pt-1.5 pb-1 text-[9.5px] font-bold uppercase tracking-wider text-text-tertiary">Project members · {members.length}</div>
                    {members.map(m => (
                        <div key={m.id} className="group flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-bg-hover">
                            {avatar(m)}
                            <div className="flex-1 min-w-0">
                                <div style={{ fontSize: 12.5 }} className="text-text-primary truncate">{m.display_name || m.name}</div>
                                <div style={{ fontSize: 10.5 }} className="text-text-tertiary truncate">@{m.name}{m.role ? ` · ${m.role}` : ''}</div>
                            </div>
                            <button onClick={() => onRemove(m.name)} className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all" title="Remove"><X className="w-3.5 h-3.5" /></button>
                        </div>
                    ))}
                    {availableProfiles.length > 0 && (
                        <>
                            <div className="px-2 pt-2 pb-1 mt-1 border-t border-border-subtle text-[9.5px] font-bold uppercase tracking-wider text-text-tertiary">Add member</div>
                            <input
                                type="text" value={query} onChange={e => setQuery(e.target.value)}
                                placeholder="Search by name…" aria-label="Search people to add"
                                className="input w-full mb-1" style={{ padding: '6px 10px', fontSize: 12.5 }}
                            />
                            {q && matches.length === 0 && (
                                <div className="px-2 py-2 text-text-tertiary" style={{ fontSize: 12 }}>No one matches “{query.trim()}”.</div>
                            )}
                            {matches.map(p => (
                                <div key={p.id} onClick={() => { onAdd(p.name); setQuery(''); }} role="button" tabIndex={0} className="flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-bg-hover cursor-pointer">
                                    {avatar(p)}
                                    <div className="flex-1 min-w-0">
                                        <div style={{ fontSize: 12.5 }} className="text-text-primary truncate">{p.display_name || p.name}</div>
                                        <div style={{ fontSize: 10.5 }} className="text-text-tertiary truncate">@{p.name}{p.role ? ` · ${p.role}` : ''}</div>
                                    </div>
                                    <Plus className="w-3.5 h-3.5 text-text-tertiary" />
                                </div>
                            ))}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}


// Project tabs — replace the old PROJECT section of the sidebar. Calendar,
// Epics have pages; Reports has none yet, so it renders disabled.
const PROJECT_TABS = [
    { label: 'Overview', leaf: 'overview' },
    { label: 'Backlog', leaf: 'backlog' },
    { label: 'Board', leaf: 'board' },
    { label: 'Roadmap', leaf: 'roadmap' },
    { label: 'Calendar', leaf: 'calendar' },
    { label: 'Epics', leaf: 'epics' },
    { label: 'Reports' },
    { label: 'Workflow', leaf: 'workflow' },
    { label: 'Deploy', leaf: 'deploy' },
    { label: 'Settings', leaf: 'settings' },
];

function ProjectTabs({ projectId }) {
    const base = ROUTES.STUDIO_PROJECT(projectId);
    return (
        <nav aria-label="Project sections" className="flex items-end gap-1 px-4 overflow-x-auto shrink-0" style={{ scrollbarWidth: 'none' }}>
            {PROJECT_TABS.map(({ label, leaf }) => {
                const cls = 'whitespace-nowrap px-3 py-2 text-[13px] border-b-2 -mb-px transition-colors';
                if (!leaf) {
                    return <span key={label} aria-disabled="true" title="Coming soon" className={`${cls} border-transparent text-text-tertiary opacity-50 cursor-not-allowed`}>{label}</span>;
                }
                return (
                    <NavLink
                        key={label}
                        to={`${base}/${leaf}`}
                        className={({ isActive }) => `${cls} ${isActive ? 'border-accent-primary text-text-primary font-medium' : 'border-transparent text-text-secondary hover:text-text-primary'}`}
                    >
                        {label}
                    </NavLink>
                );
            })}
        </nav>
    );
}

export function ProjectLayout() {
    const { projectId } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    // Persist last-visited project so StudioDashboard's "Resume" card works.
    useEffect(() => {
        if (projectId) setCurrentProjectId(projectId);
    }, [projectId]);
    const [board, setBoard] = useState(null);
    const [members, setMembers] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [epics, setEpics] = useState([]);
    // Recent feed for the Overview tab: loaded once with the page, refreshed
    // only when the 30s limit=1 change-check sees a new newest entry.
    const [activity, setActivity] = useState([]);
    // The global New menu can navigate here with route state asking for a create modal.
    const [showCreate, setShowCreate] = useState(location.state?.create === 'task');
    const [showCreateEpic, setShowCreateEpic] = useState(location.state?.create === 'epic');
    const [searchParams, setSearchParams] = useSearchParams();
    const selectedTaskId = searchParams.get('selectedTask');
    
    const [loading, setLoading] = useState(true);
    const [isPanelEditing, setIsPanelEditing] = useState(false);
    const [pendingAction, setPendingAction] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [filterPriority, setFilterPriority] = useState('');
    const [filterAssignee, setFilterAssignee] = useState('');
    const [filterEpic, setFilterEpic] = useState('');
    const [isEditing, setIsEditing] = useState(false);
    const panelEditingRef = useRef(false);

    useEffect(() => { panelEditingRef.current = isEditing; }, [isEditing]);

    // Guarded task selection — child views (Board, Backlog) call this
    // instead of setSearchParams directly so an in-progress edit doesn't
    // get blown away silently when the user clicks another task or the
    // close button. If editing, queue the action and show ConfirmModal;
    // otherwise apply immediately.
    const requestSelectTask = useCallback((taskRefOrNull) => {
        const apply = () => {
            panelEditingRef.current = false;
            setIsEditing(false);
            const newParams = new URLSearchParams(searchParams);
            if (taskRefOrNull == null) {
                newParams.delete('selectedTask');
            } else {
                newParams.set('selectedTask', taskRefOrNull);
            }
            setSearchParams(newParams);
        };
        if (panelEditingRef.current) {
            setPendingAction(() => apply);
        } else {
            apply();
        }
    }, [searchParams, setSearchParams]);

    const loadBoard = useCallback(async () => {
        try {
            const data = await api.getBoard(projectId);
            setBoard(data);
        } catch (err) { console.error('[ProjectLayout] loadBoard error:', err); }
        finally { setLoading(false); }
    }, [projectId]);

    const loadMembers = useCallback(async () => {
        try {
            const data = await api.getProjectMembers(projectId);
            setMembers(data);
        } catch (err) { console.error('[ProjectLayout] loadMembers error:', err); }
    }, [projectId]);

    const loadProfiles = useCallback(async () => {
        try {
            const data = await api.getProfiles();
            setProfiles(data);
        } catch (err) { console.error('[ProjectLayout] loadProfiles error:', err); }
    }, []);

    const loadEpics = useCallback(async () => {
        try {
            const data = await api.getEpics(projectId);
            setEpics(data);
        } catch (err) { console.error('[ProjectLayout] loadEpics error:', err); }
    }, [projectId]);

    // Optimistic board update for fast DnD moves (AP board perf). Mutates local state immediately
    // so the card visually moves before the network roundtrip finishes. Full reload on error.
    const applyMove = useCallback((taskId, newStatus) => {
        setBoard(prev => {
            if (!prev || !prev.columns) return prev;
            const columns = {};
            let movedTask = null;
            Object.keys(prev.columns).forEach(col => {
                const list = prev.columns[col] || [];
                const idx = list.findIndex(t => String(t.id) === String(taskId) || String(t.key) === String(taskId));
                if (idx !== -1) {
                    movedTask = { ...list[idx], status: newStatus };
                    columns[col] = list.filter((_, i) => i !== idx);
                } else {
                    columns[col] = [...list];
                }
            });
            if (movedTask) {
                if (!columns[newStatus]) columns[newStatus] = [];
                columns[newStatus] = [movedTask, ...columns[newStatus]];
            }
            return { ...prev, columns };
        });
    }, []);

    const lastActivityIdRef = useRef(null);

    const checkForUpdates = useCallback(async () => {
        if (document.visibilityState !== 'visible' || !projectId) return;
        try {
            const activities = await api.getProjectActivity(projectId, 1);
            const latest = activities[0];
            if (latest && latest.id !== lastActivityIdRef.current) {
                lastActivityIdRef.current = latest.id;
                // Cheap limit=1 poll; the full feed is fetched only on change.
                api.getProjectActivity(projectId, 20).then(setActivity).catch(() => {});
                loadBoard();
                loadMembers();
                loadEpics();
            }
        } catch (err) {}
    }, [projectId, loadBoard, loadMembers, loadEpics]);

    useEffect(() => {
        const init = async () => {
            await Promise.all([loadBoard(), loadMembers(), loadProfiles(), loadEpics()]);
            try {
                const activities = await api.getProjectActivity(projectId, 20);
                if (activities[0]) lastActivityIdRef.current = activities[0].id;
                setActivity(activities || []);
            } catch (e) {}
        };
        init();
    }, [projectId]);

    const checkRef = useRef(checkForUpdates);
    useEffect(() => { checkRef.current = checkForUpdates; }, [checkForUpdates]);

    useEffect(() => {
        if (!projectId) return;
        const interval = setInterval(() => checkRef.current(), 30000);
        return () => clearInterval(interval);
    }, [projectId]);

    useEffect(() => {
        const handleOpenCreateTask = () => setShowCreate(true);
        const handleOpenCreateEpic = () => setShowCreateEpic(true);
        window.addEventListener('open-create-task', handleOpenCreateTask);
        window.addEventListener('open-create-epic', handleOpenCreateEpic);
        return () => {
            window.removeEventListener('open-create-task', handleOpenCreateTask);
            window.removeEventListener('open-create-epic', handleOpenCreateEpic);
        };
    }, []);

    const handleAddMember = useCallback(async (name) => {
        try {
            await api.addProjectMember(projectId, name);
            await loadMembers();
        } catch (err) {
            console.error('[ProjectLayout] addProjectMember error:', err);
            alert('Failed to add member: ' + err.message);
        }
    }, [projectId, loadMembers]);

    const handleRemoveMember = async (name) => {
        if (!confirm(`Remove ${name} from project?`)) return;
        try {
            await api.removeProjectMember(projectId, name);
            loadMembers();
        } catch (err) { alert(err.message); }
    };

    const memberNames = new Set(members.map(m => m.name));
    const availableProfiles = profiles.filter(p => !memberNames.has(p.name));

    const [selectedTask, setSelectedTask] = useState(null);

    useEffect(() => {
        if (!selectedTaskId) {
            setSelectedTask(null);
            return;
        }
        let cancelled = false;
        if (board) {
            const found = Object.values(board.columns).flat().find(t => String(t.id) === String(selectedTaskId) || String(t.key) === String(selectedTaskId));
            if (found) {
                setSelectedTask(found);
            }
        }
        // Board cards intentionally carry a compact payload. Always replace the
        // optimistic card with the complete task so side-panel relationships
        // (parent, subtasks, dependencies, milestone) cannot appear incomplete.
        api.getTask(selectedTaskId)
            .then(task => { if (!cancelled) setSelectedTask(task); })
            .catch(err => console.error('Failed to fetch selected task:', err));
        return () => { cancelled = true; };
    }, [selectedTaskId, board]);

    if (loading) return <div className="p-8 text-center text-text-secondary">Loading project...</div>;
    if (!board) return <div className="p-8 text-center text-text-secondary">Project not found</div>;

    // Filters context
    const filters = {
        searchQuery, filterPriority, filterAssignee, filterEpic, board, epics,
        members, activity, availableProfiles, onAddMember: handleAddMember,
        reloadBoard: loadBoard,
        applyMove,
        requestSelectTask,
    };

    // Every project page gets the key/name/tabs header; search + filters only on board views.
    const isBoardView = /\/(board|backlog|roadmap)(\/|$)/.test(location.pathname)
        || /\/project\/[^/]+\/?$/.test(location.pathname);
    const isOverview = /\/overview(\/|$)/.test(location.pathname);
    const isDeployView = /\/deploy(\/|$)/.test(location.pathname);

    return (
        <div className={`flex flex-row h-full ${isDeployView ? '' : 'overflow-hidden'} w-full relative`}>
            <div className={`flex flex-col flex-1 ${isDeployView ? '' : 'overflow-hidden'} min-w-0`}>
                <header className="shrink-0 border-b">
                    <nav aria-label="Breadcrumb" className="px-4 pt-3 flex items-center gap-2 text-[13px] text-text-tertiary">
                        <Link to={ROUTES.STUDIO} className="hover:text-accent-primary">Home</Link>
                        <span>/</span>
                        <span className="truncate">{board.project.name}</span>
                    </nav>
                    <div className="px-4 pt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
                        <span className="text-[11px] font-bold tracking-wider rounded-md px-2 py-1 bg-bg-app border text-text-secondary" style={{ fontFamily: 'ui-monospace,monospace' }}>{board.project.key_prefix || 'PROJ'}</span>
                        <h2 className="text-title-lg font-medium truncate min-w-0">{board.project.name}</h2>
                        {!isOverview && (
                            <MembersControl
                                members={members}
                                availableProfiles={availableProfiles}
                                onAdd={handleAddMember}
                                onRemove={handleRemoveMember}
                            />
                        )}
                    </div>
                    <ProjectTabs projectId={projectId} />
                </header>

                {isBoardView && (
                    <BoardToolbar
                        projectId={projectId}
                        members={members}
                        epics={epics}
                        searchQuery={searchQuery} setSearchQuery={setSearchQuery}
                        filterPriority={filterPriority} setFilterPriority={setFilterPriority}
                        filterAssignee={filterAssignee} setFilterAssignee={setFilterAssignee}
                        filterEpic={filterEpic} setFilterEpic={setFilterEpic}
                        onCreate={() => setShowCreate(true)}
                    />
                )}

                <div className={`flex-1 ${isDeployView ? 'overflow-auto' : 'overflow-hidden'} relative`}>
                    <Outlet context={filters} />
                </div>
            </div>

            {selectedTask && (
                <TaskDetailPanel
                    task={selectedTask}
                    isEditing={isEditing}
                    setIsEditing={setIsEditing}
                    onSelectTask={requestSelectTask}
                    onClose={() => requestSelectTask(null)}
                    onUpdate={loadBoard}
                />
            )}

            {pendingAction && (
                <ConfirmModal
                    title="Unsaved Changes"
                    message="You have unsaved changes on this task. Are you sure you want to discard them?"
                    confirmText="Discard"
                    cancelText="Keep Editing"
                    onConfirm={() => {
                        const fn = pendingAction;
                        setPendingAction(null);
                        fn();
                    }}
                    onCancel={() => setPendingAction(null)}
                />
            )}

            {showCreate && <CreateTaskModal projectId={projectId} onClose={() => setShowCreate(false)} onCreated={loadBoard} />}
            {showCreateEpic && <CreateEpicModal projectId={projectId} onClose={() => setShowCreateEpic(false)} onCreated={loadEpics} />}
        </div>
    );
}
