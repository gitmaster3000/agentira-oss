import React, { useEffect, useState, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { useParams, useSearchParams, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { TaskDetailPanel } from '../components/TaskDetailPanel';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { ConfirmModal } from '../components/ConfirmModal';
import { UserPlus, X, Search, ChevronDown } from 'lucide-react';
import { CreateEpicModal } from '../components/CreateEpicModal';
import { ROUTES } from '../routes';

// Portal Dropdown
function AddMemberDropdown({ anchorRef, profiles, onAdd, onClose }) {
    const menuRef = useRef(null);
    const [pos, setPos] = useState({ top: 0, left: 0 });

    useEffect(() => {
        if (anchorRef.current) {
            const rect = anchorRef.current.getBoundingClientRect();
            setPos({ top: rect.bottom + 4, left: rect.left });
        }
    }, [anchorRef]);

    useEffect(() => {
        function handler(e) {
            if (
                menuRef.current && !menuRef.current.contains(e.target) &&
                anchorRef.current && !anchorRef.current.contains(e.target)
            ) {
                onClose();
            }
        }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [onClose, anchorRef]);

    return ReactDOM.createPortal(
        <div ref={menuRef} className="dropdown-menu" style={{ position: 'fixed', top: pos.top, left: pos.left, width: 240, zIndex: 99999 }}>
            <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-text-tertiary border-b border-border-subtle">
                Add Member
            </div>
            {profiles.length === 0 ? (
                <div className="p-5 text-xs text-center text-text-tertiary">
                    Everyone is already a member
                </div>
            ) : (
                <div className="max-h-60 overflow-y-auto">
                    {profiles.map(p => (
                        <div key={p.id} onClick={() => { onAdd(p.name); }} role="button" tabIndex={0} className="dropdown-item px-3 py-2.5">
                            <div style={{
                                width: 28, height: 28, borderRadius: '50%',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                fontSize: 12, fontWeight: 700, flexShrink: 0,
                                backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)',
                            }}>
                                {(p.display_name || p.name)[0]?.toUpperCase()}
                            </div>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {p.display_name || p.name}
                                </div>
                                <div style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>
                                    @{p.name} · {p.role}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>,
        document.body
    );
}

// Filter Dropdown
function FilterDropdown({ label, value, options, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const selectedLabel = options.find(o => o.value === value)?.label || label;

    useEffect(() => {
        function handler(e) {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen(v => !v)}
                className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-label-lg transition-colors ${
                    value ? 'border-accent-primary text-text-primary bg-bg-app' : 'text-text-secondary bg-bg-app hover:border-border-active hover:text-text-primary'
                }`}
            >
                <span>{selectedLabel}</span>
                <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>
            {open && (
                <div className="dropdown-menu top-full left-0 mt-1 min-w-[140px]">
                    {options.map(opt => (
                        <button
                            key={opt.value}
                            className={`dropdown-item ${value === opt.value ? 'text-accent-primary font-medium' : ''}`}
                            onClick={() => { onChange(opt.value); setOpen(false); }}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}

export function ProjectLayout() {
    const { projectId } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    // Persist last-visited project so StudioDashboard's "Resume" card works.
    useEffect(() => {
        if (projectId) {
            try { localStorage.setItem('agentira:studio:lastProjectId', projectId); } catch {}
        }
    }, [projectId]);
    const [board, setBoard] = useState(null);
    const [members, setMembers] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [epics, setEpics] = useState([]);
    const [showCreate, setShowCreate] = useState(false);
    const [showCreateEpic, setShowCreateEpic] = useState(false);
    const [searchParams, setSearchParams] = useSearchParams();
    const selectedTaskId = searchParams.get('selectedTask');
    
    const [loading, setLoading] = useState(true);
    const [showAddMember, setShowAddMember] = useState(false);
    const [isPanelEditing, setIsPanelEditing] = useState(false);
    const [pendingAction, setPendingAction] = useState(null);
    const addBtnRef = useRef(null);
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

    const lastActivityIdRef = useRef(null);

    const checkForUpdates = useCallback(async () => {
        if (document.visibilityState !== 'visible' || !projectId) return;
        try {
            const activities = await api.getProjectActivity(projectId, 1);
            const latest = activities[0];
            if (latest && latest.id !== lastActivityIdRef.current) {
                lastActivityIdRef.current = latest.id;
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
                const activities = await api.getProjectActivity(projectId, 1);
                if (activities[0]) lastActivityIdRef.current = activities[0].id;
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
            setShowAddMember(false);
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
        if (board) {
            const found = Object.values(board.columns).flat().find(t => String(t.id) === String(selectedTaskId) || String(t.key) === String(selectedTaskId));
            if (found) {
                setSelectedTask(found);
                return;
            }
        }
        api.getTask(selectedTaskId).then(setSelectedTask).catch(err => console.error('Failed to fetch selected task:', err));
    }, [selectedTaskId, board]);

    if (loading) return <div className="p-8 text-center text-text-secondary">Loading project...</div>;
    if (!board) return <div className="p-8 text-center text-text-secondary">Project not found</div>;

    // Filters context
    const filters = {
        searchQuery, filterPriority, filterAssignee, filterEpic, board,
        reloadBoard: loadBoard,
        requestSelectTask,
    };

    return (
        <div className="flex flex-row h-full overflow-hidden w-full relative">
            <div className="flex flex-col flex-1 overflow-hidden min-w-0">
                <header className="px-4 py-3 flex flex-col md:flex-row justify-between items-start md:items-center shrink-0 gap-4 border-b">
                    <div className="flex-1 min-w-0">
                        <h2 className="text-title-lg font-medium truncate">{board.project.name}</h2>
                        <p className="text-body-sm mb-3 truncate text-text-secondary">{board.project.description || "No description"}</p>

                        <div className="flex flex-wrap items-center gap-4 mt-2">
                            <div className="flex items-center gap-1">
                                {members.map(m => (
                                    <div key={m.id} className="relative group" title={`${m.display_name} (@${m.name})`}>
                                        <div className="w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold cursor-default bg-accent-subtle text-accent-primary border-bg-panel">
                                            {(m.display_name || m.name)[0]?.toUpperCase()}
                                        </div>
                                        <button onClick={() => handleRemoveMember(m.name)} className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500 text-white items-center justify-center text-[8px] hidden group-hover:flex shadow">
                                            <X className="w-2.5 h-2.5" />
                                        </button>
                                    </div>
                                ))}

                                <button ref={addBtnRef} onClick={() => setShowAddMember(v => !v)} className="w-8 h-8 rounded-full border-2 border-dashed flex items-center justify-center transition-colors hover:bg-white/10 border-border-subtle text-text-tertiary">
                                    <UserPlus className="w-3.5 h-3.5" />
                                </button>

                                {showAddMember && <AddMemberDropdown anchorRef={addBtnRef} profiles={availableProfiles} onAdd={handleAddMember} onClose={() => setShowAddMember(false)} />}
                            </div>
                            
                            <div className="flex flex-wrap items-center gap-2">
                                <div className="flex items-center relative group">
                                    <Search className="w-4 h-4 absolute left-3 text-text-tertiary group-focus-within:text-accent-primary transition-colors" />
                                    <input type="text" placeholder="Search tasks..." className="bg-bg-app border rounded-xl pl-9 pr-3 py-2 text-body-md w-48 lg:w-64 focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary transition-all text-text-primary" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} />
                                </div>
                                <FilterDropdown label="Priority" value={filterPriority} onChange={setFilterPriority} options={[{ value: '', label: 'All Priorities' }, { value: 'low', label: 'Low' }, { value: 'medium', label: 'Medium' }, { value: 'high', label: 'High' }, { value: 'critical', label: 'Critical' }]} />
                                <FilterDropdown label="Assignee" value={filterAssignee} onChange={setFilterAssignee} options={[{ value: '', label: 'All Assignees' }, ...members.map(m => ({ value: m.name, label: m.display_name || m.name }))]} />
                                <FilterDropdown label="Epic" value={filterEpic} onChange={setFilterEpic} options={[{ value: '', label: 'All Epics' }, ...epics.map(ep => ({ value: ep.id, label: ep.title }))]} />
                                {(searchQuery || filterPriority || filterAssignee || filterEpic) && (
                                    <button onClick={() => { setSearchQuery(''); setFilterPriority(''); setFilterAssignee(''); setFilterEpic(''); }} className="text-xs text-text-secondary hover:text-text-primary transition-colors px-2 py-1">Clear</button>
                                )}
                            </div>
                        </div>
                    </div>
                </header>

                <div className="flex-1 overflow-hidden relative">
                    <Outlet context={filters} />
                </div>
            </div>

            {selectedTask && (
                <TaskDetailPanel
                    task={selectedTask}
                    isEditing={isEditing}
                    setIsEditing={setIsEditing}
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
