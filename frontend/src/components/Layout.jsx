import React, { useState, useEffect, useCallback } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { ThemeToggle } from './ThemeToggle';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { CreateProjectModal } from './CreateProjectModal';
import { Pencil, Trash2, Plus, Settings, LogOut, FolderKanban, ChevronRight } from 'lucide-react';

export function Layout() {
    const { user, logout } = useAuth();
    const [projects, setProjects] = useState([]);
    const [showCreate, setShowCreate] = useState(false);
    const navigate = useNavigate();

    const loadProjects = useCallback(async () => {
        try {
            const data = await api.getProjects();
            setProjects(data);
        } catch (err) {
            console.error(err);
        }
    }, []);

    useEffect(() => {
        loadProjects();
        const interval = setInterval(loadProjects, 5000);
        return () => clearInterval(interval);
    }, [loadProjects]);

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    const handleDelete = async (id, name) => {
        if (!confirm(`Delete project "${name}" and all its tasks?`)) return;
        try {
            await api.deleteProject(id);
            loadProjects();
            navigate('/');
        } catch (err) {
            alert(err.message);
        }
    };

    const handleRename = async (id) => {
        const newName = prompt('New project name:');
        if (!newName?.trim()) return;
        try {
            await api.updateProject(id, { name: newName.trim() });
            loadProjects();
        } catch (err) {
            alert(err.message);
        }
    };

    return (
        <div className="flex h-screen overflow-hidden">
            {/* Sidebar */}
            <aside className="w-64 flex flex-col" style={{ backgroundColor: 'var(--bg-panel)', borderRight: '1px solid var(--border-subtle)' }}>
                <div className="p-4" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <h1 className="text-xl font-bold flex items-center gap-2">
                        <span style={{ color: 'var(--accent-primary)' }}>Agent</span>IRA
                    </h1>
                </div>

                <nav className="flex-1 p-2 overflow-y-auto">
                    <div className="mb-4">
                        <h3 className="text-xs uppercase font-semibold px-3 mb-2 flex items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
                            <FolderKanban className="w-3 h-3" /> Projects
                        </h3>
                        <ul className="flex flex-col gap-0.5">
                            {projects.map(p => (
                                <li key={p.id} className="group relative">
                                    <NavLink
                                        to={`/board/${p.id}`}
                                        className="flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors w-full"
                                        style={({ isActive }) => ({
                                            backgroundColor: isActive ? 'var(--accent-subtle)' : 'transparent',
                                            color: isActive ? 'var(--accent-primary)' : 'var(--text-secondary)',
                                        })}
                                    >
                                        <span className="truncate flex-1">{p.name}</span>
                                        <span className="text-xs opacity-60">{p.task_count}</span>
                                    </NavLink>
                                    {/* Hover actions */}
                                    <div className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover:flex gap-0.5">
                                        <button
                                            onClick={(e) => { e.stopPropagation(); handleRename(p.id); }}
                                            className="p-1 rounded text-xs hover:bg-white/10 transition-colors"
                                            title="Rename"
                                            style={{ color: 'var(--text-secondary)' }}
                                        ><Pencil className="w-3 h-3" /></button>
                                        <button
                                            onClick={(e) => { e.stopPropagation(); handleDelete(p.id, p.name); }}
                                            className="p-1 rounded text-xs hover:bg-red-500/10 text-red-400 transition-colors"
                                            title="Delete"
                                        ><Trash2 className="w-3 h-3" /></button>
                                    </div>
                                </li>
                            ))}
                        </ul>

                        <button
                            onClick={() => setShowCreate(true)}
                            className="w-full text-left flex items-center gap-2 px-3 py-2 rounded text-sm transition-colors mt-2 hover:bg-white/5"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            <Plus className="w-3.5 h-3.5" /> New Project
                        </button>
                    </div>
                </nav>

                <div className="p-3 space-y-1" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                    <button
                        onClick={() => navigate('/settings')}
                        className="w-full flex items-center gap-2 px-2 py-2 rounded text-sm transition-colors hover:bg-white/5 group"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <div className="w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}>
                            {user?.display_name?.[0]?.toUpperCase() || 'U'}
                        </div>
                        <div className="text-left overflow-hidden flex-1">
                            <div className="font-medium truncate text-sm" style={{ color: 'var(--text-primary)' }}>{user?.display_name}</div>
                            <div className="text-xs capitalize" style={{ color: 'var(--text-secondary)' }}>{user?.role}</div>
                        </div>
                        <ChevronRight className="w-4 h-4 opacity-0 group-hover:opacity-60 transition-opacity flex-shrink-0" />
                    </button>
                    <div className="flex items-center gap-1 px-2">
                        <button
                            onClick={handleLogout}
                            className="p-1.5 rounded hover:bg-white/10 transition-colors flex items-center gap-1.5 text-xs"
                            title="Logout"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            <LogOut className="w-3.5 h-3.5" /> Log out
                        </button>
                        <div className="flex-1" />
                        <ThemeToggle />
                    </div>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 flex flex-col overflow-hidden relative">
                <Outlet />
            </main>

            {showCreate && <CreateProjectModal onClose={() => setShowCreate(false)} onSuccess={loadProjects} />}
        </div>
    );
}
