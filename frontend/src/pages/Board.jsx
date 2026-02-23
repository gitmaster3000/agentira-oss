import React, { useEffect, useState, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { TaskCard } from '../components/TaskCard';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { TaskDetailPanel } from '../components/TaskDetailPanel';
import { ConfirmModal } from '../components/ConfirmModal';
import { UserPlus, X, Plus } from 'lucide-react';

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
            style={{
                position: 'fixed',
                top: pos.top,
                left: pos.left,
                width: 240,
                backgroundColor: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 8,
                boxShadow: '0 12px 40px rgba(0,0,0,0.5)',
                zIndex: 99999,
                overflow: 'hidden',
            }}
        >
            <div style={{ padding: '8px 12px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-tertiary)', borderBottom: '1px solid var(--border-subtle)' }}>
                Add Member
            </div>
            {profiles.length === 0 ? (
                <div style={{ padding: '20px 12px', fontSize: 12, textAlign: 'center', color: 'var(--text-tertiary)' }}>
                    Everyone is already a member
                </div>
            ) : (
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                    {profiles.map(p => (
                        <div
                            key={p.id}
                            onClick={() => { console.log('[Dropdown] clicked:', p.name); onAdd(p.name); }}
                            role="button"
                            tabIndex={0}
                            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', cursor: 'pointer', transition: 'background 0.15s' }}
                            onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.06)'; }}
                            onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent'; }}
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
    const [isPanelEditing, setIsPanelEditing] = useState(false);
    const [pendingAction, setPendingAction] = useState(null);
    const addBtnRef = useRef(null);

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

    if (loading) return <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>Loading board...</div>;
    if (!board) return <div className="p-8 text-center" style={{ color: 'var(--text-secondary)' }}>Project not found</div>;

    return (
        <div className="flex flex-row h-full overflow-hidden w-full relative">
            {/* Main Content Area: Header + Columns */}
            <div className="flex flex-col flex-1 overflow-hidden min-w-0">
                {/* Header */}
                <header className="p-4 flex justify-between items-start shrink-0" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <div className="flex-1">
                        <h2 className="text-xl font-bold">{board.project.name}</h2>
                        <p className="text-sm mb-3" style={{ color: 'var(--text-secondary)' }}>{board.project.description || "No description"}</p>

                        {/* Members row */}
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
                    </div>
                </header>

                {/* Main Content Area: Columns */}
                <div className="flex flex-1 overflow-hidden min-w-0 relative">
                    {/* Board Columns Container */}
                    <div className="flex-1 overflow-x-auto overflow-y-hidden p-4">
                        <div className="flex gap-4 h-full min-w-max">
                            {COLUMNS.map(col => (
                                <div
                                    key={col.id}
                                    className="w-72 flex flex-col rounded-lg border"
                                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)' }}
                                    onDragOver={e => e.preventDefault()}
                                    onDrop={e => handleDrop(e, col.id)}
                                >
                                    <div className="p-3 font-semibold text-sm flex justify-between items-center" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                                        {col.label}
                                        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--bg-app)', color: 'var(--text-secondary)' }}>
                                            {board.columns[col.id]?.length || 0}
                                        </span>
                                    </div>

                                    <div className="flex-1 overflow-y-auto p-2 scrollbar-hide">
                                        {board.columns[col.id]?.map(task => (
                                            <TaskCard
                                                key={task.id}
                                                task={task}
                                                onUpdate={(t) => {
                                                    if (isPanelEditing && selectedTaskId && String(t.id) !== String(selectedTaskId)) {
                                                        setPendingAction(() => () => {
                                                            setIsPanelEditing(false);
                                                            const newParams = new URLSearchParams(searchParams);
                                                            newParams.set('selectedTask', t.id);
                                                            setSearchParams(newParams);
                                                        });
                                                        return;
                                                    }
                                                    setIsPanelEditing(false);
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
                        if (isPanelEditing) {
                            setPendingAction(() => () => {
                                setIsPanelEditing(false);
                                const newParams = new URLSearchParams(searchParams);
                                newParams.delete('selectedTask');
                                setSearchParams(newParams);
                            });
                            return;
                        }
                        const newParams = new URLSearchParams(searchParams);
                        newParams.delete('selectedTask');
                        setSearchParams(newParams);
                    }}
                    onUpdate={() => {
                        loadBoard();
                    }}
                    onEditingChange={setIsPanelEditing}
                />
            )}

            {showCreate && (
                <CreateTaskModal
                    projectId={projectId}
                    onClose={() => setShowCreate(false)}
                    onCreated={loadBoard}
                />
            )}

            {pendingAction && (
                <ConfirmModal
                    title="Unsaved Changes"
                    message="You have unsaved edits. Are you sure you want to discard them?"
                    confirmText="Discard"
                    cancelText="Keep Editing"
                    isDanger={true}
                    onConfirm={() => { pendingAction(); setPendingAction(null); }}
                    onCancel={() => setPendingAction(null)}
                />
            )}
        </div>
    );
}
