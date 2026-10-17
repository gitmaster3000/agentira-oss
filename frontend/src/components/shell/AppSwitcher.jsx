import React, { useState, useRef, useEffect } from 'react';
import { CONNECTED_APPS, openConnectedApp } from '../../connectedApps';
import { useCurrentProjectId } from '../../currentProject';

// App switcher: a grid button in the top bar listing Agentira plus connected apps.
// Config is static (connectedApps.js) so the menu is fully populated on the first frame.
function Tile({ name, current, onClick, description }) {
    return (
        <div className="dropdown-item" onClick={onClick} aria-current={current ? 'true' : undefined} role="menuitem">
            <span style={{ width: '30px', height: '30px', borderRadius: '9px', background: current ? 'linear-gradient(135deg,var(--brand-lavender),var(--brand-teal))' : 'var(--tint-lavender)', color: current ? 'var(--surface-base)' : 'var(--brand-lavender)', fontSize: '14px', fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{name[0].toUpperCase()}</span>
            <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: '12.5px', fontWeight: 600 }}>{name}{current && <span style={{ marginLeft: '6px', fontSize: '10px', color: 'var(--text-muted)', fontWeight: 500 }}>current</span>}</div>
                {description && <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{description}</div>}
            </div>
        </div>
    );
}

export function AppSwitcher({ apps = CONNECTED_APPS, onOpen = openConnectedApp }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const projectId = useCurrentProjectId();

    useEffect(() => {
        const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
    }, []);

    if (!apps.length) return null;

    return (
        <div style={{ position: 'relative', flexShrink: 0 }} ref={ref}>
            <button onClick={() => setOpen((o) => !o)} aria-label="Switch app" aria-haspopup="menu" aria-expanded={open} title="Apps"
                className="hovertint" style={{ background: 'none', border: 'none', padding: '7px', color: 'var(--text-tertiary)', cursor: 'pointer', borderRadius: '9px', display: 'flex' }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">{[5, 12, 19].flatMap((x) => [5, 12, 19].map((y) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.9" />))}</svg>
            </button>
            {open && (
                <div className="dropdown-menu" role="menu" style={{ top: '100%', left: 0, marginTop: '8px', width: '250px' }}>
                    <Tile name="Agentira" description="Work, agents & runs" current onClick={() => setOpen(false)} />
                    <div style={{ height: '1px', background: 'var(--overlay-tint)', margin: '5px 4px' }} />
                    {apps.map((a) => <Tile key={a.key} name={a.name} description={a.description} onClick={() => { setOpen(false); onOpen(a, { project: projectId || '' }); }} />)}
                </div>
            )}
        </div>
    );
}
