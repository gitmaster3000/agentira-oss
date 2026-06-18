import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { api } from '../../api';
import { useCurrentProjectId } from '../../currentProject';
import { useShellData } from './shellData';

// Exact port of Agentira.dc.html top bar (design hash RjjZ09618cpj5TzJmourRQ).
// Breadcrumb, "N running" pulse pill, New menu and bell are all wired to real
// data / real actions — no prototype mock rows.

const crumbSeg = (txt, dim) => (
    <span style={{ color: dim ? '#768390' : '#f0f3f6', fontWeight: dim ? 400 : 600 }}>{txt}</span>
);
const Chev = () => (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#768390" strokeWidth="2"><path d="M9 18l6-6-6-6" /></svg>
);

// Derive a real breadcrumb from the current route + active project name.
function useBreadcrumb(activeProjectName) {
    const path = useLocation().pathname;
    const seg = (leaf) => {
        const map = {
            board: 'Board', backlog: 'Backlog', roadmap: 'Roadmap',
            overview: 'Overview', settings: 'Settings',
        };
        return map[leaf];
    };
    if (path === '/studio' || path === '/') return [crumbSeg('Home')];
    if (path.startsWith('/studio/settings')) return [crumbSeg('Settings')];
    if (path.startsWith('/studio/project/')) {
        const leaf = path.split('/').pop();
        const label = seg(leaf) || 'Project';
        return [crumbSeg(activeProjectName || 'Project', true), <Chev key="c" />, crumbSeg(label)];
    }
    if (path.startsWith('/studio/tasks/')) return [crumbSeg(activeProjectName || 'Project', true), <Chev key="c" />, crumbSeg('Board', true), <Chev key="c2" />, crumbSeg('Task')];
    if (path.startsWith('/forge/agents')) return [crumbSeg('Build', true), <Chev key="c" />, crumbSeg('Agents')];
    if (path.startsWith('/forge/runs')) return [crumbSeg('Build', true), <Chev key="c" />, crumbSeg('Runs')];
    if (path.startsWith('/forge/conductor')) return [crumbSeg('Build', true), <Chev key="c" />, crumbSeg('Conductor')];
    if (path.startsWith('/forge/runtimes')) return [crumbSeg('Build', true), <Chev key="c" />, crumbSeg('Runtimes')];
    if (path.startsWith('/forge/settings')) return [crumbSeg('Build', true), <Chev key="c" />, crumbSeg('Build Settings')];
    if (path === '/forge') return [crumbSeg('Build', true), <Chev key="c" />, crumbSeg('Overview')];
    return [crumbSeg('Home')];
}

export function AppTopbar({ onNewProject }) {
    const navigate = useNavigate();
    const { projectId: urlProjectId } = useParams();
    const storedProjectId = useCurrentProjectId();
    const { projects, runningTotal, pulseOpen, togglePulse } = useShellData();
    const activeProjectId = urlProjectId || storedProjectId;
    const activeProject = projects.find((p) => p.id === activeProjectId);
    const crumb = useBreadcrumb(activeProject?.name);

    const [newOpen, setNewOpen] = useState(false);
    const [bellOpen, setBellOpen] = useState(false);
    const [notifs, setNotifs] = useState([]);
    const newRef = useRef(null);
    const bellRef = useRef(null);

    const unread = notifs.filter((n) => !n.read).length;

    useEffect(() => {
        let cancelled = false;
        const load = async () => {
            try {
                const data = await api.getNotifications(false);
                if (!cancelled) setNotifs(Array.isArray(data) ? data : []);
            } catch { /* ignore */ }
        };
        load();
        const id = setInterval(load, 30_000);
        const onDown = (e) => {
            if (newRef.current && !newRef.current.contains(e.target)) setNewOpen(false);
            if (bellRef.current && !bellRef.current.contains(e.target)) setBellOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => { cancelled = true; clearInterval(id); document.removeEventListener('mousedown', onDown); };
    }, []);

    const onNotifClick = async (n) => {
        try {
            if (!n.read) {
                await api.markNotificationRead(n.id);
                setNotifs((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
            }
            if (n.link) navigate(n.link);
        } finally {
            setBellOpen(false);
        }
    };

    const createItem = (tint, stroke, icon, title, sub, onClick) => (
        <div className="nav" onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '9px 10px', borderRadius: '9px', cursor: 'pointer', color: 'inherit' }}>
            <span style={{ width: '30px', height: '30px', borderRadius: '8px', background: tint, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2">{icon}</svg>
            </span>
            <div>
                <div style={{ fontSize: '12.5px', fontWeight: 600 }}>{title}</div>
                <div style={{ fontSize: '10.5px', color: '#768390' }}>{sub}</div>
            </div>
        </div>
    );

    return (
        <header style={{ height: '54px', flexShrink: 0, borderBottom: '1px solid #30363d', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 18px', background: '#0e1117', fontFamily: 'var(--font-sans)', WebkitFontSmoothing: 'antialiased' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', minWidth: 0 }}>{crumb}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
                {/* Pulse pill — toggles the full-height Pulse drawer (PulseDock).
                    Pulse blue when something is running; muted "All quiet" otherwise.
                    Always clickable so the drawer can be pulled out / dismissed. */}
                <div
                    onClick={togglePulse}
                    title={pulseOpen ? 'Hide Pulse' : 'Show Pulse'}
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px', borderRadius: '999px', background: runningTotal > 0 ? 'rgba(56,189,248,.08)' : (pulseOpen ? '#1c2128' : 'transparent'), border: `1px solid ${runningTotal > 0 ? 'rgba(56,189,248,.3)' : '#30363d'}`, cursor: 'pointer' }}
                >
                    {runningTotal > 0 ? (
                        <>
                            <span style={{ position: 'relative', display: 'inline-flex' }}>
                                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#38bdf8' }} />
                                <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: '#38bdf8', animation: 'livedot 1.8s ease-out infinite' }} />
                            </span>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#38bdf8' }}>{runningTotal} running</span>
                        </>
                    ) : (
                        <>
                            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#768390' }} />
                            <span style={{ fontSize: '12px', fontWeight: 600, color: '#768390' }}>Live status</span>
                        </>
                    )}
                </div>

                {/* New menu */}
                <div style={{ position: 'relative' }} ref={newRef}>
                    <div onClick={() => setNewOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '7px 13px', borderRadius: '10px', background: '#c9b8ff', color: '#2d1a6e', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}>
                        <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 5v14M5 12h14" /></svg>New
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M6 9l6 6 6-6" /></svg>
                    </div>
                    {newOpen && (
                        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '230px', background: '#1c2128', border: '1px solid #30363d', borderRadius: '12px', boxShadow: '0 16px 40px rgba(0,0,0,.55)', zIndex: 50, padding: '6px' }}>
                            {createItem('rgba(128,203,196,.14)', '#80cbc4', (<><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /></>), 'New task', 'File work on the board', () => { setNewOpen(false); window.dispatchEvent(new CustomEvent('open-create-task')); })}
                            {createItem('rgba(197,138,249,.14)', '#c58af9', (<><rect x="3" y="4" width="18" height="6" rx="1" /><rect x="3" y="14" width="18" height="6" rx="1" /></>), 'New epic', 'Group tasks on the roadmap', () => { setNewOpen(false); window.dispatchEvent(new CustomEvent('open-create-epic')); })}
                            {createItem('rgba(201,184,255,.14)', '#c9b8ff', (<path d="M3 7v13h18V7M3 7l2-3h14l2 3M3 7h18" />), 'New project', 'Guided 5-step wizard', () => { setNewOpen(false); onNewProject && onNewProject(); })}
                        </div>
                    )}
                </div>

                {/* Bell */}
                <div style={{ position: 'relative' }} ref={bellRef}>
                    <div onClick={() => setBellOpen((o) => !o)} style={{ position: 'relative', padding: '7px', color: '#b1bac4', cursor: 'pointer' }}>
                        <svg className="ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
                        {unread > 0 && <span style={{ position: 'absolute', top: '4px', right: '4px', width: '7px', height: '7px', borderRadius: '50%', background: '#ef4444', border: '2px solid #0e1117' }} />}
                    </div>
                    {bellOpen && (
                        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '312px', background: '#1c2128', border: '1px solid #30363d', borderRadius: '12px', boxShadow: '0 16px 40px rgba(0,0,0,.55)', zIndex: 50, overflow: 'hidden' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '11px 14px', borderBottom: '1px solid #30363d' }}>
                                <span style={{ fontSize: '12.5px', fontWeight: 700 }}>Notifications</span>
                                {unread > 0 && <span style={{ fontSize: '11px', fontWeight: 700, background: '#ef4444', color: '#fff', borderRadius: '999px', padding: '1px 7px' }}>{unread}</span>}
                            </div>
                            <div style={{ padding: '5px', maxHeight: '320px', overflowY: 'auto' }}>
                                {notifs.length === 0 ? (
                                    <div style={{ padding: '24px 8px', textAlign: 'center', fontSize: '12px', color: '#768390' }}>You're all caught up.</div>
                                ) : notifs.slice(0, 8).map((n) => (
                                    <div key={n.id} className="nav" onClick={() => onNotifClick(n)} style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '9px', borderRadius: '9px', cursor: 'pointer', opacity: n.read ? 0.6 : 1 }}>
                                        <span style={{ marginTop: '1px', width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0, background: n.read ? 'transparent' : '#ef4444' }} />
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <div style={{ fontSize: '12.5px', color: '#e8ebf0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title}</div>
                                            <div style={{ fontSize: '11px', color: '#768390', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.type}{n.created_at ? ` · ${new Date(n.created_at).toLocaleString()}` : ''}</div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div className="nav" onClick={() => { setBellOpen(false); navigate('/studio'); }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '10px', borderTop: '1px solid #30363d', fontSize: '12px', fontWeight: 600, color: '#c9b8ff', cursor: 'pointer' }}>
                                Open Inbox<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </header>
    );
}
