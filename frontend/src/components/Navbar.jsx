import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams, Link, useLocation } from 'react-router-dom';
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
    CheckSquare,
    Pencil,
    Cpu,
} from 'lucide-react';

const PRODUCTS = {
    studio: { name: 'Studio', icon: Pencil, color: '#d0bcff', path: '/' },
    forge:  { name: 'Forge',  icon: Cpu,    color: '#80cbc4', path: '/forge' },
};

export function Navbar({ onNewProject }) {
    const { user, logout } = useAuth();
    const { projectId } = useParams();
    const location = useLocation();
    const activeProduct = PRODUCTS[location.pathname.startsWith('/forge') ? 'forge' : 'studio'];
    const ActiveIcon = activeProduct.icon;
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
        <header className="h-16 border-b bg-bg-panel flex items-center px-4 justify-between z-50 sticky top-0">
            <div className="flex items-center gap-5">
                {/* Logo */}
                <Link to={activeProduct.path} className="flex items-center gap-2.5 hover:opacity-80 transition-opacity">
                    <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ backgroundColor: activeProduct.color + '1a' }}>
                        <ActiveIcon className="w-5 h-5" style={{ color: activeProduct.color }} />
                    </span>
                    <div className="hidden md:flex flex-col leading-tight">
                        <span className="text-[10px] font-medium tracking-widest uppercase" style={{ color: 'var(--text-tertiary)' }}>Flowty</span>
                        <span className="text-title-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{activeProduct.name}</span>
                    </div>
                </Link>

                {/* Project Switcher */}
                <div className="relative" ref={projectRef}>
                    <button
                        onClick={() => setIsProjectOpen(!isProjectOpen)}
                        className="flex items-center gap-2 px-3 py-2 rounded-xl border text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors text-label-lg"
                    >
                        <Briefcase className="w-4 h-4" />
                        <span className="text-text-primary whitespace-nowrap max-w-[150px] truncate">
                            {activeProject ? activeProject.name : 'Select Project'}
                        </span>
                        <ChevronDown className={`w-3 h-3 transition-transform ${isProjectOpen ? 'rotate-180' : ''}`} />
                    </button>

                    {isProjectOpen && (
                        <div className="dropdown-menu top-full left-0 mt-1 w-64">
                            <div className="px-3 py-2 text-label-sm text-text-tertiary uppercase tracking-wider">Recent Projects</div>
                            <div className="max-h-64 overflow-y-auto">
                                {projects.map(p => (
                                    <button
                                        key={p.id}
                                        onClick={() => {
                                            navigate(`/board/${p.id}`);
                                            setIsProjectOpen(false);
                                        }}
                                        className={`dropdown-item px-3 ${p.id === projectId ? 'text-text-primary font-medium' : 'text-text-secondary'}`}
                                    >
                                        <div className="w-7 h-7 rounded-md border bg-bg-panel flex items-center justify-center text-label-sm font-bold text-text-secondary">
                                            {p.name[0].toUpperCase()}
                                        </div>
                                        <span className="truncate flex-1">{p.name}</span>
                                        {p.id === projectId && <div className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--accent-primary)' }} />}
                                    </button>
                                ))}
                            </div>
                            <div className="border-t mt-1 pt-1">
                                <button
                                    onClick={() => { onNewProject(); setIsProjectOpen(false); }}
                                    className="dropdown-item px-3 text-text-secondary hover:text-text-primary gap-2"
                                >
                                    <Plus className="w-4 h-4" /> Create Project
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
            <div className="flex items-center gap-2">
                {/* Create Dropdown */}
                <div className="relative" ref={createRef}>
                    <button
                        onClick={() => setIsCreateOpen(!isCreateOpen)}
                        className="p-2 rounded-xl border hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors flex items-center gap-1"
                        title="Create new"
                    >
                        <Plus className="w-5 h-5" />
                        <ChevronDown className={`w-3 h-3 transition-transform ${isCreateOpen ? 'rotate-180' : ''}`} />
                    </button>

                    {isCreateOpen && (
                        <div className="dropdown-menu top-full right-0 mt-1 w-48">
                            {projectId && (
                                <button
                                    onClick={() => {
                                        window.dispatchEvent(new CustomEvent('open-create-task'));
                                        setIsCreateOpen(false);
                                    }}
                                    className="dropdown-item"
                                >
                                    <CheckSquare className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} /> Task
                                </button>
                            )}
                            <button
                                onClick={() => {
                                    onNewProject();
                                    setIsCreateOpen(false);
                                }}
                                className="dropdown-item"
                            >
                                <Briefcase className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} /> Project
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
                        className="bg-bg-app border rounded-xl pl-9 pr-3 py-2 text-body-md w-48 lg:w-64 focus:outline-none focus:border-accent-primary focus:ring-1 focus:ring-accent-primary transition-all text-text-primary"
                    />
                </div>

                <div className="flex items-center gap-1 border-l pl-3 ml-1">
                    <button className="p-2 rounded-xl hover:bg-bg-hover text-text-secondary relative transition-colors">
                        <Bell className="w-5 h-5" />
                        <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
                    </button>
                    <ThemeToggle />
                    <AppSwitcher />

                    {/* User Menu */}
                    <div className="relative ml-1" ref={userRef}>
                        <button
                            onClick={() => setIsUserOpen(!isUserOpen)}
                            className="w-9 h-9 rounded-full flex items-center justify-center font-medium text-sm transition-all"
                            style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--accent-primary)' }}
                        >
                            {user?.display_name?.[0]?.toUpperCase() || 'U'}
                        </button>

                        {isUserOpen && (
                            <div className="dropdown-menu top-full right-0 mt-1 w-56">
                                <div className="px-4 py-3 border-b mb-1">
                                    <div className="text-title-sm text-text-primary">{user?.display_name}</div>
                                    <div className="text-body-sm text-text-tertiary truncate">{user?.name}</div>
                                </div>
                                <button
                                    onClick={() => { navigate('/settings'); setIsUserOpen(false); }}
                                    className="dropdown-item text-text-secondary hover:text-text-primary"
                                >
                                    <Settings className="w-4 h-4" /> Settings
                                </button>
                                <button
                                    onClick={handleLogout}
                                    className="dropdown-item text-red-400 hover:bg-red-500/10"
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
