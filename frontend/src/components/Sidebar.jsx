import React, { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
    LayoutGrid,
    ListTodo,
    TrendingUp,
    ChevronLeft,
    ChevronRight,
} from 'lucide-react';

export function Sidebar() {
    const { projectId = 'default' } = useParams();
    const [searchParams] = useSearchParams();
    const currentView = searchParams.get('view') || 'board';

    const [isCollapsed, setIsCollapsed] = useState(() => {
        return localStorage.getItem('sidebar-collapsed') === 'true';
    });

    const toggleSidebar = () => {
        const newState = !isCollapsed;
        setIsCollapsed(newState);
        localStorage.setItem('sidebar-collapsed', JSON.stringify(newState));
    };

    const navItems = [
        { icon: LayoutGrid, label: 'Board', path: `/board/${projectId}`, view: 'board' },
        { icon: ListTodo, label: 'Backlog', path: `/board/${projectId}?view=backlog`, view: 'backlog' },
        { icon: TrendingUp, label: 'Roadmap', path: `/board/${projectId}?view=roadmap`, view: 'roadmap' },
    ];

    return (
        <aside
            className={`flex flex-col border-r bg-bg-panel transition-all duration-300 ease-in-out absolute top-0 left-0 h-full z-20 ${isCollapsed ? 'w-[72px]' : 'w-64 shadow-xl'}`}
        >
            {/* Toggle */}
            <button
                onClick={toggleSidebar}
                className="absolute -right-3 top-5 w-6 h-6 rounded-full bg-bg-card border flex items-center justify-center hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-all shadow-elevation-1 z-10"
            >
                {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>

            <div className="flex-1 py-3 flex flex-col gap-0.5 overflow-x-hidden">
                {!isCollapsed && (
                    <div className="px-4 mb-3 text-label-sm text-text-tertiary uppercase tracking-wider">
                        Planning
                    </div>
                )}

                {navItems.map((item) => {
                    const isActive = currentView === item.view;
                    return (
                        <Link
                            key={item.label}
                            to={item.path}
                            className={`flex items-center gap-3 mx-3 px-3 py-2.5 rounded-xl transition-all
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
