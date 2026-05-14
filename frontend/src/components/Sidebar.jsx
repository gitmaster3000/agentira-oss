import React, { useState } from 'react';
import { Link, useParams, useLocation } from 'react-router-dom';
import {
    LayoutGrid,
    ListTodo,
    TrendingUp,
    PanelLeft,
} from 'lucide-react';
import { ROUTES } from '../routes';

export function Sidebar() {
    const { projectId = 'default' } = useParams();
    const location = useLocation();

    // Check if we are inside a project route to highlight nav items properly
    const isProjectRoute = location.pathname.includes('/studio/project/');

    const [isCollapsed, setIsCollapsed] = useState(() => {
        return localStorage.getItem('sidebar-collapsed') === 'true';
    });

    const toggleSidebar = () => {
        const newState = !isCollapsed;
        setIsCollapsed(newState);
        localStorage.setItem('sidebar-collapsed', JSON.stringify(newState));
    };

    const navItems = [
        { icon: LayoutGrid, label: 'Board', path: ROUTES.STUDIO_PROJECT_BOARD(projectId), view: 'board' },
        { icon: ListTodo, label: 'Backlog', path: ROUTES.STUDIO_PROJECT_BACKLOG(projectId), view: 'backlog' },
        { icon: TrendingUp, label: 'Roadmap', path: ROUTES.STUDIO_PROJECT_ROADMAP(projectId), view: 'roadmap' },
    ];

    return (
        <aside
            className={`flex flex-col border-r bg-bg-panel transition-all duration-300 ease-in-out h-full relative group ${isCollapsed ? 'w-16' : 'w-64'}`}
        >
            <div className="flex-1 py-3 flex flex-col gap-0.5 overflow-x-hidden">
                <div className={`flex items-center px-4 mb-4 ${isCollapsed ? 'justify-center mb-6' : 'justify-between'}`}>
                    {!isCollapsed && (
                        <span className="text-title-sm font-bold text-text-primary uppercase tracking-wider">
                            Planning
                        </span>
                    )}
                    <button
                        onClick={toggleSidebar}
                        className="p-1.5 rounded-lg text-text-secondary hover:bg-bg-hover hover:text-accent-primary transition-all"
                        title={isCollapsed ? "Expand" : "Collapse"}
                    >
                        <PanelLeft className="w-5 h-5 flex-shrink-0" />
                    </button>
                </div>

                {isProjectRoute && navItems.map((item) => {
                    const isActive = location.pathname === item.path;
                    return (
                        <Link
                            key={item.label}
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
                })}
            </div>
        </aside>
    );
}
