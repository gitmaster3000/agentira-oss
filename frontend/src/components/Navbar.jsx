import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams, Link, useLocation } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { ROUTES } from '../routes';
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
    Zap,
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
    const [notifications, setNotifications] = useState([]);
    const [isNotifOpen, setIsNotifOpen] = useState(false);
    const projectRef = useRef(null);
    const userRef = useRef(null);
    const createRef = useRef(null);
    const notifRef = useRef(null);

    const unreadCount = notifications.filter(n => !n.read).length;

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
            if (notifRef.current && !notifRef.current.contains(event.target)) {
                setIsNotifOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [projectId]);

    // Poll notifications every 30s. Inbox view requests both read + unread
    // so the dropdown can show recent history. Per ADR-007 this is the
    // poll half of the push+poll hybrid.
    useEffect(() => {
        let cancelled = false;
        const fetchNotifs = async () => {
            try {
                const data = await api.getNotifications(false);
                if (!cancelled) setNotifications(Array.isArray(data) ? data : []);
            } catch (err) {
                // 401 or network — silently ignore, retry next tick
            }
        };
        fetchNotifs();
        const id = setInterval(fetchNotifs, 30_000);
        return () => { cancelled = true; clearInterval(id); };
    }, []);

    const handleNotifClick = async (n) => {
        try {
            if (!n.read) {
                await api.markNotificationRead(n.id);
                setNotifications(prev => prev.map(x => x.id === n.id ? { ...x, read: true } : x));
            }
            if (n.link) navigate(n.link);
        } finally {
            setIsNotifOpen(false);
        }
    };

    const handleMarkAllRead = async () => {
        const unread = notifications.filter(x => !x.read);
        await Promise.all(unread.map(n => api.markNotificationRead(n.id).catch(() => {})));
        setNotifications(prev => prev.map(x => ({ ...x, read: true })));
    };

    const handleLogout = () => {
        logout();
        navigate(ROUTES.LOGIN);
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
                        <span className="text-[10px] font-medium tracking-widest uppercase" style={{ color: 'var(--text-tertiary)' }}>AgentIRA</span>
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
                                            navigate(ROUTES.STUDIO_BOARD(p.id));
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
                                <>
                                    <button
                                        onClick={() => {
                                            window.dispatchEvent(new CustomEvent('open-create-task'));
                                            setIsCreateOpen(false);
                                        }}
                                        className="dropdown-item"
                                    >
                                        <CheckSquare className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} /> Task
                                    </button>
                                    <button
                                        onClick={() => {
                                            window.dispatchEvent(new CustomEvent('open-create-epic'));
                                            setIsCreateOpen(false);
                                        }}
                                        className="dropdown-item"
                                    >
                                        <Zap className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} /> Epic
                                    </button>
                                </>
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
                    {/* Notifications */}
                    <div className="relative" ref={notifRef}>
                        <button
                            onClick={() => setIsNotifOpen(o => !o)}
                            className="p-2 rounded-xl hover:bg-bg-hover text-text-secondary relative transition-colors"
                            aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : 'Notifications'}
                        >
                            <Bell className="w-5 h-5" />
                            {unreadCount > 0 && (
                                <span
                                    className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold flex items-center justify-center"
                                >
                                    {unreadCount > 99 ? '99+' : unreadCount}
                                </span>
                            )}
                        </button>

                        {isNotifOpen && (
                            <div className="dropdown-menu top-full right-0 mt-1 w-80">
                                <div className="px-3 py-2 border-b mb-1 flex items-center justify-between">
                                    <span className="text-label-sm text-text-tertiary uppercase tracking-wider">Notifications</span>
                                    {unreadCount > 0 && (
                                        <button
                                            onClick={handleMarkAllRead}
                                            className="text-label-sm text-text-tertiary hover:text-text-primary"
                                        >
                                            Mark all read
                                        </button>
                                    )}
                                </div>
                                <div className="max-h-96 overflow-y-auto">
                                    {notifications.length === 0 ? (
                                        <div className="px-3 py-8 text-center text-body-sm text-text-tertiary">
                                            You're all caught up.
                                        </div>
                                    ) : (
                                        notifications.slice(0, 25).map(n => (
                                            <button
                                                key={n.id}
                                                onClick={() => handleNotifClick(n)}
                                                className={`w-full text-left px-3 py-2 hover:bg-bg-hover transition-colors flex gap-2 items-start ${n.read ? 'opacity-60' : ''}`}
                                            >
                                                <span
                                                    className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${n.read ? 'bg-transparent' : 'bg-red-500'}`}
                                                />
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-body-sm text-text-primary truncate">{n.title}</div>
                                                    <div className="text-label-sm text-text-tertiary mt-0.5">
                                                        {n.type}
                                                        {n.created_at && ` · ${new Date(n.created_at).toLocaleString()}`}
                                                    </div>
                                                </div>
                                            </button>
                                        ))
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
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
                                    onClick={() => { navigate(ROUTES.STUDIO_SETTINGS); setIsUserOpen(false); }}
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
