import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectKey } from './shellData';

const KEY_CHIP = { fontSize: '10px', fontWeight: 700, background: 'var(--tint-lavender)', color: 'var(--brand-lavender)', borderRadius: '5px', padding: '2px 5px', flexShrink: 0 };

// Project switcher: pill next to Work | Build showing the active project; the menu
// lists the projects already loaded by ShellDataProvider (no fetch on open).
export function ProjectSwitcher({ projects, active }) {
    const navigate = useNavigate();
    const [open, setOpen] = useState(false);
    const ref = useRef(null);

    useEffect(() => {
        const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
    }, []);

    if (!active) return null;

    return (
        <div style={{ position: 'relative', flexShrink: 0, minWidth: 0 }} ref={ref}>
            <button onClick={() => setOpen((o) => !o)} aria-label={`Switch project, current: ${active.name}`} aria-haspopup="menu" aria-expanded={open}
                className="hoverline" style={{ display: 'flex', alignItems: 'center', gap: '7px', maxWidth: '200px', padding: '5px 10px', borderRadius: '9px', border: '1px solid var(--overlay-line)', background: 'none', color: 'var(--text-primary)', fontSize: '12.5px', fontWeight: 600, fontFamily: 'inherit', cursor: 'pointer' }}>
                <span style={KEY_CHIP}>{projectKey(active)}</span>
                <span className="shell-hide-sm" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{active.name}</span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" style={{ flexShrink: 0, color: 'var(--text-muted)' }}><path d="M6 9l6 6 6-6" /></svg>
            </button>
            {open && (
                <div className="dropdown-menu" role="menu" style={{ top: '100%', left: 0, marginTop: '8px', width: '250px', maxHeight: '320px', overflowY: 'auto' }}>
                    {projects.map((p) => (
                        <div key={p.id} className="dropdown-item" role="menuitem" tabIndex={0} aria-current={p.id === active.id ? 'true' : undefined}
                            onClick={() => { setOpen(false); navigate(`/studio/project/${p.id}/board`); }}
                            onKeyDown={(e) => { if (e.key === 'Enter') { setOpen(false); navigate(`/studio/project/${p.id}/board`); } }}>
                            <span style={KEY_CHIP}>{projectKey(p)}</span>
                            <span style={{ flex: 1, minWidth: 0, fontSize: '12.5px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                            {p.id === active.id && <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>current</span>}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
