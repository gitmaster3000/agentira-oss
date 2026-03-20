import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { TaskDetailPanel } from '../components/TaskDetailPanel';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { CreateEpicModal } from '../components/CreateEpicModal';
import { ChevronDown, ChevronRight, UserPlus, Zap, Tag } from 'lucide-react';

export function Backlog({ projectId }) {
    const [tasks, setTasks] = useState([]);
    const [epics, setEpics] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [filterStatus, setFilterStatus] = useState('');
    const [filterAssignee, setFilterAssignee] = useState('');
    const [sortKey, setSortKey] = useState('created_at');
    const [sortDirection, setSortDirection] = useState('desc');
    const [searchParams, setSearchParams] = useSearchParams();
    const selectedTaskId = searchParams.get('selectedTask');
    const [isEditing, setIsEditing] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [showCreateEpic, setShowCreateEpic] = useState(false);
    const [collapsedSections, setCollapsedSections] = useState({});
    const [groupBy, setGroupBy] = useState('epic'); // 'epic' or 'tag'

    const fetchTasks = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const epicsPromise = api.getEpics(projectId).catch(err => {
                console.warn('Epics load failed:', err);
                return [];
            });
            const tasksPromise = api.listTasks(projectId, filterStatus || undefined, filterAssignee || undefined).catch(err => {
                console.error('Tasks load failed:', err);
                return [];
            });

            const [fetchedEpics, fetchedTasks] = await Promise.all([epicsPromise, tasksPromise]);

            const sortedTasks = [...fetchedTasks].sort((a, b) => {
                let valA = a[sortKey];
                let valB = b[sortKey];
                if (sortKey === 'priority') {
                    const order = { critical: 4, high: 3, medium: 2, low: 1 };
                    valA = order[a.priority?.toLowerCase()] || 0;
                    valB = order[b.priority?.toLowerCase()] || 0;
                }
                if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
                if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
                return 0;
            });

            setTasks(sortedTasks);
            setEpics(fetchedEpics);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [projectId, filterStatus, filterAssignee, sortKey, sortDirection]);

    const lastActivityIdRef = React.useRef(null);

    const checkForUpdates = React.useCallback(async () => {
        if (document.visibilityState !== 'visible' || !projectId) return;
        try {
            const activities = await api.getProjectActivity(projectId, 1);
            const latest = activities[0];
            if (latest && latest.id !== lastActivityIdRef.current) {
                lastActivityIdRef.current = latest.id;
                fetchTasks();
            }
        } catch (err) {
            console.error('[Backlog] checkForUpdates error:', err);
        }
    }, [projectId]);

    const checkRef = React.useRef(checkForUpdates);
    useEffect(() => { checkRef.current = checkForUpdates; }, [checkForUpdates]);

    useEffect(() => {
        const init = async () => {
            await fetchTasks();
            try {
                const activities = await api.getProjectActivity(projectId, 1);
                if (activities[0]) lastActivityIdRef.current = activities[0].id;
            } catch (e) {}
        };
        init();
    }, [projectId, filterStatus, filterAssignee, sortKey, sortDirection]);

    useEffect(() => {
        if (!projectId) return;
        const interval = setInterval(() => checkRef.current(), 30000); // Stable 30s
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

    const selectedTask = selectedTaskId ? tasks.find(t => String(t.id) === String(selectedTaskId)) : null;

    const toggleSection = (id) => setCollapsedSections(prev => ({ ...prev, [id]: !prev[id] }));

    // Grouping logic
    let sections = [];
    if (groupBy === 'epic') {
        const grouped = {};
        epics.forEach(ep => { grouped[ep.id] = { id: ep.id, title: ep.title, color: ep.color, tasks: [], type: 'epic' }; });
        grouped['__none__'] = { id: '__none__', title: 'Ungrouped', tasks: [], type: 'none' };
        tasks.forEach(task => {
            const key = task.epic_id && grouped[task.epic_id] ? task.epic_id : '__none__';
            grouped[key].tasks.push(task);
        });
        sections = [
            ...epics.filter(ep => grouped[ep.id].tasks.length > 0).map(ep => grouped[ep.id]),
            ...epics.filter(ep => grouped[ep.id].tasks.length === 0).map(ep => grouped[ep.id]),
            grouped['__none__'],
        ];
    } else {
        // Group by Tag
        const grouped = {};
        tasks.forEach(task => {
            const tag = task.tags && task.tags.length > 0 ? task.tags[0] : 'No Tag';
            if (!grouped[tag]) grouped[tag] = { id: tag, title: tag, tasks: [], type: 'tag' };
            grouped[tag].tasks.push(task);
        });
        sections = Object.values(grouped).sort((a, b) => a.title.localeCompare(b.title));
    }

    const priorityColors = { critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#22c55e' };

    return (
        <div className="flex flex-row h-full w-full overflow-hidden bg-bg-app">
            <div className="flex flex-col flex-1 overflow-hidden min-w-0">
                {/* Header */}
                <div className="px-6 py-4 border-b shrink-0" style={{ borderColor: 'var(--border-subtle)' }}>
                    <div className="flex items-center justify-between mb-3">
                        <h1 className="text-xl font-medium" style={{ color: 'var(--text-primary)' }}>Backlog</h1>
                        
                        {/* Group By Toggle */}
                        <div className="flex bg-bg-panel p-1 rounded-xl border border-border-subtle">
                            <button
                                className={`px-3 py-1 text-[11px] font-bold uppercase tracking-wider rounded-lg transition-all ${groupBy === 'epic' ? 'bg-bg-app text-accent-primary shadow-sm' : 'text-text-tertiary hover:text-text-secondary'}`}
                                onClick={() => setGroupBy('epic')}
                            >
                                Epics
                            </button>
                            <button
                                className={`px-3 py-1 text-[11px] font-bold uppercase tracking-wider rounded-lg transition-all ${groupBy === 'tag' ? 'bg-bg-app text-accent-primary shadow-sm' : 'text-text-tertiary hover:text-text-secondary'}`}
                                onClick={() => setGroupBy('tag')}
                            >
                                Tags
                            </button>
                        </div>
                    </div>

                    {/* Filters */}
                    <div className="flex items-center gap-4 flex-wrap">
                        <select
                            className="input"
                            style={{ width: 'auto', minWidth: 120, padding: '8px 36px 8px 14px', fontSize: 13 }}
                            value={filterStatus}
                            onChange={e => setFilterStatus(e.target.value)}
                        >
                            <option value="">All Statuses</option>
                            <option value="backlog">Backlog</option>
                            <option value="todo">To Do</option>
                            <option value="in_progress">In Progress</option>
                            <option value="review">Review</option>
                            <option value="done">Done</option>
                        </select>
                        <input
                            className="input"
                            style={{ width: 160, padding: '8px 14px', fontSize: 13 }}
                            type="text"
                            placeholder="Filter assignee..."
                            value={filterAssignee}
                            onChange={e => setFilterAssignee(e.target.value)}
                        />
                        <select
                            className="input"
                            style={{ width: 'auto', minWidth: 120, padding: '8px 36px 8px 14px', fontSize: 13 }}
                            value={sortKey}
                            onChange={e => setSortKey(e.target.value)}
                        >
                            <option value="created_at">Sort: Created</option>
                            <option value="priority">Sort: Priority</option>
                        </select>
                        <button
                            className="btn-ghost"
                            style={{ padding: '6px 12px', fontSize: 13, borderRadius: 12 }}
                            onClick={() => setSortDirection(d => d === 'asc' ? 'desc' : 'asc')}
                        >
                            {sortDirection === 'asc' ? '↑ Asc' : '↓ Desc'}
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-6 py-4">
                    {loading && <div className="p-8 text-center text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading backlog...</div>}
                    {error && <div className="p-4 text-center text-sm" style={{ color: '#ef4444' }}>Error: {error}</div>}

                    {!loading && sections.map((section) => {
                        const isCollapsed = collapsedSections[section.id];
                        return (
                            <div key={section.id} className="mb-3">
                                <div
                                    className="flex items-center gap-2 px-3 py-2.5 rounded-t-md cursor-pointer hover:bg-bg-hover transition-colors"
                                    style={{ backgroundColor: 'var(--bg-panel)', border: '1px solid var(--border-subtle)' }}
                                    onClick={() => toggleSection(section.id)}
                                >
                                    {isCollapsed ? <ChevronRight className="w-4 h-4 text-text-tertiary" /> : <ChevronDown className="w-4 h-4 text-text-tertiary" />}
                                    
                                    {section.type === 'epic' ? <Zap className="w-3.5 h-3.5" style={{ color: section.color || '#7c4dff' }} /> : <Tag className="w-3.5 h-3.5 text-text-tertiary" />}
                                    
                                    <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{section.title}</span>
                                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full ml-1" style={{ color: 'var(--text-tertiary)', backgroundColor: 'var(--bg-hover)' }}>{section.tasks.length}</span>
                                </div>

                                {!isCollapsed && (
                                    <div style={{ border: '1px solid var(--border-subtle)', borderTop: 'none', borderRadius: '0 0 8px 8px', backgroundColor: 'var(--bg-panel)', overflow: 'hidden' }}>
                                        {section.tasks.length === 0 && <div className="px-4 py-3 text-xs italic text-text-tertiary">No issues</div>}
                                        {section.tasks.map((task, idx) => {
                                            const pColor = priorityColors[task.priority?.toLowerCase()] || '#888';
                                            return (
                                                <div
                                                    key={task.id}
                                                    onClick={() => {
                                                        const newParams = new URLSearchParams(searchParams);
                                                        newParams.set('selectedTask', task.id);
                                                        setSearchParams(newParams);
                                                    }}
                                                    className={`flex items-center px-4 py-2 hover:bg-bg-hover cursor-pointer transition-colors ${selectedTaskId === String(task.id) ? 'bg-bg-hover' : ''}`}
                                                    style={{ borderBottom: idx !== section.tasks.length - 1 ? '1px solid var(--border-subtle)' : 'none' }}
                                                >
                                                    <div className="w-3 h-3 rounded-sm mr-3 flex-shrink-0" style={{ backgroundColor: `var(--status-${task.status}, var(--text-tertiary))` }} />
                                                    
                                                    <div className="flex items-center gap-2 flex-1 min-w-0 mr-3">
                                                        <span className="text-sm truncate font-medium" style={{ color: 'var(--text-primary)' }}>{task.title}</span>
                                                        
                                                        {/* Epic/Tag pills inside row */}
                                                        {task.epic_name && (
                                                            <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-sm flex-shrink-0" style={{ backgroundColor: `${task.epic_color || '#7c4dff'}20`, color: task.epic_color || '#7c4dff' }}>
                                                                {task.epic_name}
                                                            </span>
                                                        )}
                                                        {task.tags && task.tags.slice(0, 2).map(t => (
                                                            <span key={t} className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded-sm flex-shrink-0 border border-border-subtle text-text-tertiary bg-bg-app">
                                                                {t}
                                                            </span>
                                                        ))}
                                                    </div>

                                                    <span className="text-[10px] font-bold uppercase mr-4 px-1.5 py-0.5 rounded flex-shrink-0" style={{ color: pColor, backgroundColor: pColor + '18' }}>{task.priority || '—'}</span>

                                                    {task.assignee ? (
                                                        <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}>{task.assignee[0].toUpperCase()}</div>
                                                    ) : (
                                                        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 border border-dashed border-border-active text-text-tertiary"><UserPlus className="w-3 h-3" /></div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
