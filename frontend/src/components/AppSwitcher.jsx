import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { LayoutGrid, Cpu, Pencil } from 'lucide-react';

const PRODUCTS = [
    {
        id: 'studio',
        name: 'Studio',
        description: 'Workspace & tasks',
        icon: Pencil,
        path: '/',
        color: '#7c4dff',
    },
    {
        id: 'forge',
        name: 'Forge',
        description: 'Agent orchestration',
        icon: Cpu,
        path: '/forge',
        color: '#00bcd4',
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
                className="p-1.5 rounded-md hover:bg-bg-hover text-text-secondary hover:text-text-primary transition-colors"
                title="Switch app"
            >
                <LayoutGrid className="w-5 h-5" />
            </button>

            {open && (
                <div className="absolute top-full left-0 mt-2 w-64 bg-bg-card border border-border-subtle rounded-lg shadow-2xl py-2 z-[70] animate-fade-in">
                    <div className="px-4 py-2 text-xs font-semibold text-text-tertiary uppercase tracking-wider">
                        Flowty Apps
                    </div>
                    {PRODUCTS.map((p) => (
                        <button
                            key={p.id}
                            onClick={() => {
                                navigate(p.path);
                                setOpen(false);
                            }}
                            className={`w-full text-left px-4 py-3 flex items-center gap-3 transition-colors hover:bg-bg-hover ${
                                activeProduct === p.id ? 'bg-bg-hover' : ''
                            }`}
                        >
                            <div
                                className="w-9 h-9 rounded-lg flex items-center justify-center"
                                style={{ backgroundColor: p.color + '18' }}
                            >
                                <p.icon className="w-5 h-5" style={{ color: p.color }} />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium text-text-primary">{p.name}</div>
                                <div className="text-xs text-text-tertiary">{p.description}</div>
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
