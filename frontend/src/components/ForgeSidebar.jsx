import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
    Bot,
    Play,
    BarChart3,
    Cpu,
    ChevronLeft,
    ChevronRight,
} from 'lucide-react';

export function ForgeSidebar() {
    const location = useLocation();

    const [isCollapsed, setIsCollapsed] = useState(() => {
        return localStorage.getItem('forge-sidebar-collapsed') === 'true';
    });

    const toggleSidebar = () => {
        const newState = !isCollapsed;
        setIsCollapsed(newState);
        localStorage.setItem('forge-sidebar-collapsed', JSON.stringify(newState));
    };

    const navItems = [
        { icon: BarChart3, label: 'Overview', path: '/forge' },
        { icon: Bot, label: 'Agents', path: '/forge/agents' },
        { icon: Cpu, label: 'Runtimes', path: '/forge/runtimes' },
        { icon: Play, label: 'Runs', path: '/forge/runs' },
    ];

    return (
        <aside
            className={`flex flex-col border-r border-border-subtle bg-bg-panel transition-all duration-300 ease-in-out relative ${isCollapsed ? 'w-16' : 'w-64'}`}
        >
            <button
                onClick={toggleSidebar}
                className="absolute -right-3 top-4 w-6 h-6 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-all shadow-md z-10"
            >
                {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>

            <div className="flex-1 py-4 flex flex-col gap-1 overflow-x-hidden">
                {!isCollapsed && (
                    <div className="px-4 mb-4 text-xs font-semibold text-text-tertiary uppercase tracking-wider">
                        Forge
                    </div>
                )}

                {navItems.map((item) => {
                    const isActive = location.pathname === item.path;
                    return (
                        <Link
                            key={item.label}
                            to={item.path}
                            className={`flex items-center gap-3 px-4 py-2.5 transition-all
                                ${isActive ? 'bg-accent-subtle text-accent-primary border-r-2 border-accent-primary' : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'}
                            `}
                            title={isCollapsed ? item.label : ''}
                        >
                            <item.icon className="w-5 h-5 flex-shrink-0" />
                            {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">{item.label}</span>}
                        </Link>
                    );
                })}
            </div>
        </aside>
    );
}
