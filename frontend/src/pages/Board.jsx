import React, { useEffect, useState, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { TaskCard } from '../components/TaskCard';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { TaskDetailPanel } from '../components/TaskDetailPanel';
import { UserPlus, X, Plus, Search, ChevronDown } from 'lucide-react';

const COLUMNS = [
    { id: 'backlog', label: 'Backlog' },
    { id: 'todo', label: 'To Do' },
    { id: 'in_progress', label: 'In Progress' },
    { id: 'review', label: 'Review' },
    { id: 'done', label: 'Done' },
];

/* ─── Portal Dropdown ───────────────────────────────────────────────── */
function AddMemberDropdown({ anchorRef, profiles, onAdd, onClose }) {
    const menuRef = useRef(null);
    const [pos, setPos] = useState({ top: 0, left: 0 });

    // Position the dropdown below the anchor button
    useEffect(() => {
        if (anchorRef.current) {
            const rect = anchorRef.current.getBoundingClientRect();
            setPos({ top: rect.bottom + 4, left: rect.left });
        }
    }, [anchorRef]);

    // Click outside → close
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
        <div
            ref={menuRef}
            className="dropdown-menu"
            style={{ position: 'fixed', top: pos.top, left: pos.left, width: 240, zIndex: 99999 }}
        >
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
                        <div
                            key={p.id}
                            onClick={() => { console.log('[Dropdown] clicked:', p.name); onAdd(p.name); }}
                            role="button"
                            tabIndex={0}
                            className="dropdown-item px-3 py-2.5"
                        >
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

/* ─── Filter Dropdown ──────────────────────────────────────────────── */
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
                    value
                        ? 'border-accent-primary text-text-primary bg-bg-app'
                        : 'text-text-secondary bg-bg-app hover:border-border-active hover:text-text-primary'
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
                            className={`dropdown-item ${
                                value === opt.value ? 'text-accent-primary font-medium' : ''
                            }`}
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

/* ─── Board ─────────────────────────────────────────────────────────── */
export function Board() {
    const { projectId } = useParams();
    const [board, setBoard] = useState(null);
    const [members, setMembers] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [showCreate, setShowCreate] = useState(false);
    const [searchParams, setSearchParams] = useSearchParams();
    const selectedTaskId = searchParams.get('selectedTask');
    const [loading, setLoading] = useState(true);
    const [showAddMember, setShowAddMember] = useState(false);
    const addBtnRef = useRef(null);

    const [searchQuery, setSearchQuery] = useState('');
    const [filterPriority, setFilterPriority] = useState('');
    const [filterAssignee, setFilterAssignee] = useState('');

    const loadBoard = async () => {
        try {
            const data = await api.getBoard(projectId);
            setBoard(data);
        } catch (err) { console.error('[Board] loadBoard error:', err); }
        finally { setLoading(false); }
    };

    const loadMembers = async () => {
        try {
            const data = await api.getProjectMembers(projectId);
            console.log('[Board] members loaded:', data?.length);
            setMembers(data);
        } catch (err) { console.error('[Board] loadMembers error:', err); }
    };

    const loadProfiles = async () => {
        try {
            const data = await api.getProfiles();
            console.log('[Board] profiles loaded:', data?.length, data?.map(p => p.name));
            setProfiles(data);
        } catch (err) { console.error('[Board] loadProfiles error:', err); }
    };

    useEffect(() => {
        loadBoard();
        loadMembers();
        loadProfiles();
        const interval = setInterval(() => { loadBoard(); loadMembers(); }, 5000);
        return () => clearInterval(interval);
    }, [projectId]);

    useEffect(() => {
        const handleOpenCreateTask = () => setShowCreate(true);
        window.addEventListener('open-create-task', handleOpenCreateTask);
        return () => window.removeEventListener('open-create-task', handleOpenCreateTask);
    }, []);

    const handleAddMember = useCallback(async (name) => {
        console.log('[Board] handleAddMember:', name);
        try {
            const result = await api.addProjectMember(projectId, name);
            console.log('[Board] addProjectMember result:', result);
            await loadMembers();
            setShowAddMember(false);
        } catch (err) {
            console.error('[Board] addProjectMember error:', err);
            alert('Failed to add member: ' + err.message);
        }
    }, [projectId]);

    const handleRemoveMember = async (name) => {
        if (!confirm(`Remove ${name} from project?`)) return;
        try {
            await api.removeProjectMember(projectId, name);
            loadMembers();
        } catch (err) { alert(err.message); }
    };

    const handleDrop = async (e, status) => {
        const taskId = e.dataTransfer.getData('taskId');
        if (!taskId) return;
        try {
            await api.moveTask(taskId, status);
            loadBoard();
        } catch (err) {
            alert(err.message || "Failed to move task");
            loadBoard();
        }
    };

    const memberNames = new Set(members.map(m => m.name));
    const availableProfiles = profiles.filter(p => !memberNames.has(p.name));

    // Derive selectedTask from the ID in the URL
    const selectedTask = board && selectedTaskId
        ? Object.values(board.columns).flat().find(t => String(t.id) === String(selectedTaskId))
        : null;

    const getFilteredColumns = () => {
        if (!board) return {};
        const filtered = {};
        for (const [colId, tasks] of Object.entries(board.columns)) {
            filtered[colId] = tasks.filter(task => {
                if (searchQuery && !task.title.toLowerCase().includes(searchQuery.toLowerCase())) return false;
                if (filterPriority && task.priority !== filterPriority) return false;
                if (filterAssignee && task.assignee !== filterAssignee) return false;
                return true;
            });
        }
        return filtered;
    };
    const filteredColumns = getFilteredColumns();

    if (loading) return <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>Loading board...</div>;
    if (!board) return <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>Project not found</div>;

    return (
        <div className="flex flex-row h-full overflow-hidden w-full relative">
            {/* Main Content Area: Header + Columns */}
            <div className="flex flex-col flex-1 overflow-hidden min-w-0">
                {/* Header */}
                <header className="px-4 py-3 flex flex-col md:flex-row justify-between items-start md:items-center shrink-0 gap-4 border-b">
                    <div className="flex-1 min-w-0">
                        <h2 className="text-title-lg font-medium truncate">{board.project.name}</h2>
                        <p className="text-body-sm mb-3 truncate text-text-secondary">{board.project.description || "No description"}</p>

                        {/* Members row & Filter */}
                        <div className="flex flex-wrap items-center gap-4 mt-2">
                            <div className="flex items-center gap-1">
                                {members.map(m => (
                                    <div
                                        key={m.id}
                                        className="relative group"
                                        title={`${m.display_name} (@${m.name})`}
                                    >
                                        <div
                                            className="w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-bold cursor-default"
                                            style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)', borderColor: 'var(--bg-panel)' }}
                                        >
                                            {(m.display_name || m.name)[0]?.toUpperCase()}
                                        </div>
                                        <button
                                            onClick={() => handleRemoveMember(m.name)}
                                            className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500 text-white items-center justify-center text-[8px] hidden group-hover:flex shadow"
                                            title={`Remove ${m.display_name}`}
                                        >
                                            <X className="w-2.5 h-2.5" />
                                        </button>
                                    </div>
                                ))}

                                {/* Add member button */}
                                <button
                                    ref={addBtnRef}
                                    onClick={() => { console.log('[Board] Add button clicked, available:', availableProfiles.length); setShowAddMember(v => !v); }}
                                    className="w-8 h-8 rounded-full border-2 border-dashed flex items-center justify-center transition-colors hover:bg-white/10"
                                    style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-tertiary)' }}
                                    title="Add member"
                                >
                                    <UserPlus className="w-3.5 h-3.5" />
                                </button>

                                {/* Portal dropdown */}
                                {showAddMember && (
                                    <AddMemberDropdown
                                        anchorRef={addBtnRef}
                                        profiles={availableProfiles}
                                        onAdd={handleAddMember}
                                        onClose={() => setShowAddMember(false)}
                                    />
                                )}
                            </div>
                            
                            {/* Filter Bar */}
                            <div className="flex flex-wrap items-center gap-2">
                                <div className="flex items-center relative group">
                                    <Search className="w-4 h-4 absolute left-3 text-text-tertiary group-focus-within:text-accent-primary transition-colors" />
                                    <input
                                        type="text"
                                        placeholder="Search tasks..."
                                        className="bg-bg-app border rounded-xl pl-9 pr-3 py-2 text-body-md w-48 lg:w-64 focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary transition-all text-text-primary"
                                        value={searchQuery}
                                        onChange={e => setSearchQuery(e.target.value)}
                                    />
                                </div>
                                <FilterDropdown
                                    label="Priority"
                                    value={filterPriority}
                                    onChange={setFilterPriority}
                                    options={[
                                        { value: '', label: 'All Priorities' },
                                        { value: 'low', label: 'Low' },
                                        { value: 'medium', label: 'Medium' },
                                        { value: 'high', label: 'High' },
                                        { value: 'critical', label: 'Critical' },
                                    ]}
                                />
                                <FilterDropdown
                                    label="Assignee"
                                    value={filterAssignee}
                                    onChange={setFilterAssignee}
                                    options={[
                                        { value: '', label: 'All Assignees' },
                                        ...members.map(m => ({ value: m.name, label: m.display_name || m.name }))
                                    ]}
                                />
                                {(searchQuery || filterPriority || filterAssignee) && (
                                    <button
                                        onClick={() => {
                                            setSearchQuery('');
                                            setFilterPriority('');
                                            setFilterAssignee('');
                                        }}
                                        className="text-xs text-text-secondary hover:text-text-primary transition-colors px-2 py-1"
                                    >
                                        Clear
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                </header>

                {/* Main Content Area: Columns */}
                <div className="flex flex-1 overflow-hidden min-w-0 relative">
                    {/* Board Columns Container */}
                    <div className="flex-1 overflow-x-auto overflow-y-hidden p-2 sm:p-3 lg:p-4">
                        <div className="flex gap-2 sm:gap-3 lg:gap-4 h-full min-w-max">
                            {COLUMNS.map(col => (
                                <div
                                    key={col.id}
                                    className="w-60 sm:w-64 lg:w-72 flex flex-col rounded-md h-full overflow-hidden"
                                    style={{ backgroundColor: 'var(--bg-surface-purple)' }}
                                    onDragOver={e => e.preventDefault()}
                                    onDrop={e => handleDrop(e, col.id)}
                                >
                                    <div className="px-4 py-3 font-medium text-title-sm flex justify-between items-center border-b">
                                        {col.label}
                                        <span className="text-label-sm px-2.5 py-0.5 rounded-full" style={{ backgroundColor: 'var(--bg-app)', color: 'var(--text-secondary)' }}>
                                            {filteredColumns[col.id]?.length || 0}
                                        </span>
                                    </div>

                                    <div className="flex-1 pl-4 pr-2.5 py-2 column-scroll">
                                        {filteredColumns[col.id]?.map(task => (
                                            <TaskCard
                                                key={task.id}
                                                task={task}
                                                onUpdate={(t) => {
                                                    const newParams = new URLSearchParams(searchParams);
                                                    newParams.set('selectedTask', t.id);
                                                    setSearchParams(newParams);
                                                }}
                                                onDelete={loadBoard}
                                            />
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            {/* Task Detail Panel - pushes the entire board content (Header + Columns) */}
            {selectedTask && (
                <TaskDetailPanel
                    task={selectedTask}
                    onClose={() => {
                        const newParams = new URLSearchParams(searchParams);
                        newParams.delete('selectedTask');
                        setSearchParams(newParams);
                    }}
                    onUpdate={() => {
                        loadBoard();
                    }}
                />
            )}

            {showCreate && (
                <CreateTaskModal
                    projectId={projectId}
                    onClose={() => setShowCreate(false)}
                    onCreated={loadBoard}
                />
            )}
        </div>
    );
}
