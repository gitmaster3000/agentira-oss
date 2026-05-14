import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Cpu, Pencil } from 'lucide-react';
import { ROUTES } from '../routes';

const PRODUCTS = [
    {
        id: 'studio',
        name: 'Studio',
        description: 'Workspace & tasks',
        icon: Pencil,
        path: ROUTES.STUDIO,
        color: '#d0bcff',
    },
    {
        id: 'forge',
        name: 'Forge',
        description: 'Agent orchestration',
        icon: Cpu,
        path: '/forge',
        color: '#80cbc4',
    },
];

export function AppSwitcher() {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const navigate = useNavigate();
    const location = useLocation();

    const activeProduct = location.pathname.startsWith('/forge') ? 'forge' : 'studio';

    useEffect(() => {
        const handleClickOutside = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen(!open)}
                className="p-2 rounded-xl hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
                title="Switch app"
            >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <circle cx="5" cy="5" r="2" />
                    <circle cx="12" cy="5" r="2" />
                    <circle cx="19" cy="5" r="2" />
                    <circle cx="5" cy="12" r="2" />
                    <circle cx="12" cy="12" r="2" />
                    <circle cx="19" cy="12" r="2" />
                    <circle cx="5" cy="19" r="2" />
                    <circle cx="12" cy="19" r="2" />
                    <circle cx="19" cy="19" r="2" />
                </svg>
            </button>

            {open && (
                <div className="dropdown-menu top-full right-0 mt-2 w-72 py-3 animate-fade-in">
                    <div className="px-4 py-2 text-label-sm text-text-tertiary uppercase tracking-wider">
                        AgentIRA Apps
                    </div>
                    {PRODUCTS.map((p) => (
                        <button
                            key={p.id}
                            onClick={() => {
                                navigate(p.path);
                                setOpen(false);
                            }}
                            className="w-full text-left px-4 py-3 flex items-center gap-3 transition-colors hover:bg-bg-hover text-text-secondary hover:text-text-primary"
                        >
                            <div
                                className="w-10 h-10 rounded-lg flex items-center justify-center"
                                style={{ backgroundColor: p.color + '1a' }}
                            >
                                <p.icon className="w-5 h-5" style={{ color: p.color }} />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="text-title-sm text-text-primary">{p.name}</div>
                                <div className="text-body-sm text-text-tertiary">{p.description}</div>
                            </div>
                            {activeProduct === p.id && (
                                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                            )}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
