import React, { useState } from 'react';
import { Link, useParams, useLocation } from 'react-router-dom';
import {
    LayoutGrid,
    ListTodo,
    TrendingUp,
    PanelLeft,
    Home,
    Settings as SettingsIcon,
    Bot,
    Play,
    BarChart3,
    Cpu,
    Radio,
    Workflow as WorkflowIcon,
} from 'lucide-react';
import { ROUTES } from '../routes';
import { useCurrentProjectId } from '../currentProject';

// One sidebar for the whole app. Planning items appear when a project is
// in scope; Build items always show below. Replaces the old Sidebar +
// ForgeSidebar split — see AppSwitcher removal in Navbar.
export function Sidebar() {
    const { projectId: urlProjectId } = useParams();
    const storedProjectId = useCurrentProjectId();
    const projectId = urlProjectId || storedProjectId || 'default';
    const location = useLocation();

    const isProjectRoute = location.pathname.includes('/studio/project/')
        || location.pathname.startsWith('/studio/tasks/')
        || location.pathname.startsWith('/studio/epics/');

    const [isCollapsed, setIsCollapsed] = useState(() => {
        return localStorage.getItem('sidebar-collapsed') === 'true';
    });

    const toggleSidebar = () => {
        const newState = !isCollapsed;
        setIsCollapsed(newState);
        localStorage.setItem('sidebar-collapsed', JSON.stringify(newState));
    };

    const planning = [
        { icon: Home, label: 'Overview', path: ROUTES.STUDIO_PROJECT_OVERVIEW(projectId) },
        { icon: LayoutGrid, label: 'Board', path: ROUTES.STUDIO_PROJECT_BOARD(projectId) },
        { icon: ListTodo, label: 'Backlog', path: ROUTES.STUDIO_PROJECT_BACKLOG(projectId) },
        { icon: TrendingUp, label: 'Roadmap', path: ROUTES.STUDIO_PROJECT_ROADMAP(projectId) },
        { icon: WorkflowIcon, label: 'Workflow', path: ROUTES.STUDIO_PROJECT_WORKFLOW(projectId) },
        { icon: SettingsIcon, label: 'Settings', path: ROUTES.STUDIO_PROJECT_SETTINGS(projectId) },
    ];

    const build = [
        { icon: BarChart3, label: 'Overview', path: '/forge' },
        { icon: Bot, label: 'Agents', path: '/forge/agents' },
        { icon: Radio, label: 'Conductor', path: '/forge/conductor' },
        { icon: Cpu, label: 'Runtimes', path: '/forge/runtimes' },
        { icon: Play, label: 'Runs', path: '/forge/runs' },
        { icon: SettingsIcon, label: 'Settings', path: '/forge/settings' },
    ];

    const renderItem = (item) => {
        const isActive = location.pathname === item.path;
        return (
            <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 mx-2 px-3 py-2.5 rounded-xl transition-all
                    ${isActive
                        ? 'bg-accent-subtle text-accent-primary font-medium'
                        : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'}
                `}
                title={isCollapsed ? item.label : ''}
            >
                <item.icon className="w-5 h-5 flex-shrink-0" />
                {!isCollapsed && <span className="text-label-lg whitespace-nowrap">{item.label}</span>}
            </Link>
        );
    };

    const renderHeader = (label, withToggle = false) => (
        <div className={`flex items-center px-4 mb-3 ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
            {!isCollapsed && (
                <span className="text-title-sm font-bold text-text-primary uppercase tracking-wider">
                    {label}
                </span>
            )}
            {withToggle && (
                <button
                    onClick={toggleSidebar}
                    className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-hover hover:text-accent-primary transition-all"
                    title={isCollapsed ? 'Expand' : 'Collapse'}
                >
                    <PanelLeft className="w-5 h-5 flex-shrink-0" />
                </button>
            )}
        </div>
    );

    return (
        <aside
            className={`flex flex-col border-r bg-bg-panel transition-all duration-300 ease-in-out h-full relative group ${isCollapsed ? 'w-16' : 'w-64'}`}
        >
            <div className="flex-1 py-3 flex flex-col gap-0.5 overflow-x-hidden overflow-y-auto">
                {isProjectRoute ? (
                    <>
                        {renderHeader('Planning', true)}
                        {planning.map(renderItem)}
                        <div className="my-3 mx-4 border-t border-border-subtle" />
                    </>
                ) : (
                    renderHeader('', true)
                )}

                {renderHeader('Build')}
                {build.map(renderItem)}
            </div>
        </aside>
    );
}
