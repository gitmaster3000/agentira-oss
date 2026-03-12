import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { ThemeToggle } from './ThemeToggle';
import { AppSwitcher } from './AppSwitcher';
import {
    ChevronDown,
    Plus,
    Bell,
    Settings,
    LogOut,
    Search,
    Briefcase,
    CheckSquare
} from 'lucide-react';

export function Navbar({ onNewProject }) {
    const { user, logout } = useAuth();
    const { projectId } = useParams();
    const navigate = useNavigate();
    const [projects, setProjects] = useState([]);
    const [isProjectOpen, setIsProjectOpen] = useState(false);
    const [isUserOpen, setIsUserOpen] = useState(false);
    const [isCreateOpen, setIsCreateOpen] = useState(false);
    const projectRef = useRef(null);
    const userRef = useRef(null);
    const createRef = useRef(null);

    const activeProject = projects.find(p => p.id === projectId);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.getProjects();
                setProjects(data);
            } catch (err) {
                console.error(err);
            }
        }
        load();

        const handleClickOutside = (event) => {
            if (projectRef.current && !projectRef.current.contains(event.target)) {
                setIsProjectOpen(false);
            }
            if (userRef.current && !userRef.current.contains(event.target)) {
                setIsUserOpen(false);
            }
            if (createRef.current && !createRef.current.contains(event.target)) {
                setIsCreateOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [projectId]);

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    return (
        <header className="h-14 border-b border-border-subtle bg-bg-panel flex items-center px-4 justify-between z-50 sticky top-0">
            <div className="flex items-center gap-6">
                {/* Logo */}
                <AppSwitcher />

                <Link to="/" className="flex items-center gap-2 font-bold text-lg hover:opacity-80 transition-opacity">
                    <span className="w-8 h-8 rounded bg-accent-primary flex items-center justify-center text-white">A</span>
                    <span className="hidden md:inline">Agentira</span>
                </Link>

                {/* Project Switcher */}
                <div className="relative" ref={projectRef}>
                    <button
                        onClick={() => setIsProjectOpen(!isProjectOpen)}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-border-subtle text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors text-sm font-medium"
                    >
                        <Briefcase className="w-4 h-4" />
                        <span className="text-text-primary whitespace-nowrap max-w-[150px] truncate">
                            {activeProject ? activeProject.name : 'Select Project'}
                        </span>
                        <ChevronDown className="w-3 h-3" />
                    </button>

                    {isProjectOpen && (
                        <div className="absolute top-full left-0 mt-1 w-64 bg-bg-card border border-border-subtle rounded-md shadow-2xl py-1 z-[60]">
                            <div className="px-3 py-2 text-xs font-semibold text-text-tertiary uppercase">Recent Projects</div>
                            <div className="max-h-64 overflow-y-auto">
                                {projects.map(p => (
                                    <button
                                        key={p.id}
                                        onClick={() => {
                                            navigate(`/board/${p.id}`);
                                            setIsProjectOpen(false);
                                        }}
                                        className={`w-full text-left px-3 py-2 text-sm hover:bg-bg-hover flex items-center gap-3 transition-colors ${p.id === projectId ? 'text-text-primary font-medium' : 'text-text-secondary'}`}
                                    >
                                        <div className="w-6 h-6 rounded border border-border-subtle bg-bg-panel flex items-center justify-center text-[10px] font-bold text-text-secondary">
                                            {p.name[0].toUpperCase()}
                                        </div>
                                        <span className="truncate flex-1">{p.name}</span>
                                        {p.id === projectId && <div className="w-1.5 h-1.5 rounded-full bg-text-primary" />}
                                    </button>
                                ))}
                            </div>
                            <div className="border-t border-border-subtle mt-1 pt-1">
                                <button
                                    onClick={() => { onNewProject(); setIsProjectOpen(false); }}
                                    className="w-full text-left px-3 py-2 text-sm text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors flex items-center gap-2"
                                >
                                    <Plus className="w-4 h-4" /> Create Project
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
            <div className="flex items-center gap-3">
                {/* Create Dropdown */}
                <div
                    className="relative"
                    ref={createRef}
                >
                    <button
                        onClick={() => setIsCreateOpen(!isCreateOpen)}
                        className="p-1.5 rounded-md border border-border-subtle hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors flex items-center gap-1"
                        title="Create new"
                    >
                        <Plus className="w-5 h-5" />
                        <ChevronDown className="w-3 h-3" />
                    </button>

                    {isCreateOpen && (
                        <div className="absolute top-full right-0 mt-1 w-48 bg-bg-card border border-border-subtle rounded-md shadow-2xl py-1 z-[60]">
                            {projectId && (
                                <button
                                    onClick={() => {
                                        window.dispatchEvent(new CustomEvent('open-create-task'));
                                        setIsCreateOpen(false);
                                    }}
                                    className="w-full text-left px-4 py-2 text-sm text-text-primary hover:bg-bg-hover flex items-center gap-3"
                                >
                                    <CheckSquare className="w-4 h-4 text-accent-primary" /> Task
                                </button>
                            )}
                            <button
                                onClick={() => {
                                    onNewProject();
                                    setIsCreateOpen(false);
                                }}
                                className="w-full text-left px-4 py-2 text-sm text-text-primary hover:bg-bg-hover flex items-center gap-3"
                            >
                                <Briefcase className="w-4 h-4 text-accent-primary" /> Project
                            </button>
                        </div>
                    )}
                </div>

                {/* Search Bar */}
                <div className="hidden md:flex items-center relative group">
                    <Search className="w-4 h-4 absolute left-3 text-text-tertiary group-focus-within:text-accent-primary transition-colors" />
                    <input
                        type="text"
                        placeholder="Search..."
                        className="bg-bg-app border border-border-subtle rounded-md pl-9 pr-3 py-1.5 text-sm w-48 lg:w-64 focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary transition-all"
                    />
                </div>

                <div className="flex items-center gap-1 border-l border-border-subtle pl-3 ml-2">
                    <button className="p-1.5 rounded-md border border-border-subtle hover:bg-bg-hover text-text-secondary relative">
                        <Bell className="w-5 h-5" />
                        <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full border-2 border-bg-panel" />
                    </button>
                    <ThemeToggle />

                    {/* User Menu */}
                    <div className="relative ml-2" ref={userRef}>
                        <button
                            onClick={() => setIsUserOpen(!isUserOpen)}
                            className="w-8 h-8 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-sm text-accent-primary border border-accent-primary/20 hover:border-accent-primary transition-all"
                        >
                            {user?.display_name?.[0]?.toUpperCase() || 'U'}
                        </button>

                        {isUserOpen && (
                            <div className="absolute top-full right-0 mt-1 w-56 bg-bg-card border border-border-subtle rounded-md shadow-2xl py-2 z-[60]">
                                <div className="px-4 py-2 border-b border-border-subtle mb-1">
                                    <div className="text-sm font-semibold text-text-primary">{user?.display_name}</div>
                                    <div className="text-xs text-text-tertiary truncate">{user?.name}</div>
                                </div>
                                <button
                                    onClick={() => { navigate('/settings'); setIsUserOpen(false); }}
                                    className="w-full text-left px-4 py-2 text-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary flex items-center gap-3"
                                >
                                    <Settings className="w-4 h-4" /> Settings
                                </button>
                                <button
                                    onClick={handleLogout}
                                    className="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 flex items-center gap-3"
                                >
                                    <LogOut className="w-4 h-4" /> Sign out
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </header>
    );
}
