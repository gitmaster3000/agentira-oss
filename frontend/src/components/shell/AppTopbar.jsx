import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { api } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { useCurrentProjectId, setCurrentProjectId } from '../../currentProject';
import { useShellData } from './shellData';
import { GlobalSearch } from './GlobalSearch';
import { RunNotificationLine, isRunMeta } from '../RunNotification';

// Exact port of the Agentira.dc.html top bar: blended into the canvas (no card
// chrome), holding the logo lockup, the project switcher (moved out of the
// sidebar), the breadcrumb, the search pill, and the right-hand controls.
// Work | Build switch, global New menu, breadcrumb and bell are wired to real
// data / real actions — no prototype mock rows. The "N running" pulse pill
// only shows in Build; Work has no sidebar.

const crumbSeg = (txt, dim) => (
    <span style={{ color: dim ? 'var(--text-muted)' : 'var(--text-primary)', fontWeight: dim ? 400 : 600 }}>{txt}</span>
);
const Chev = () => (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" style={{ stroke: 'var(--text-muted)' }} strokeWidth="2"><path d="M9 18l6-6-6-6" /></svg>
);

// Derive a real breadcrumb from the current route + active project name.
function useBreadcrumb(activeProjectName) {
    const path = useLocation().pathname;
    const seg = (leaf) => {
        const map = {
            board: 'Board', backlog: 'Backlog', roadmap: 'Roadmap',
            overview: 'Overview', settings: 'Settings', workflow: 'Workflow',
            deploy: 'Deploy',
        };
        return map[leaf];
    };
    if (path === '/studio' || path === '/') return [crumbSeg('Home')];
    if (path.startsWith('/studio/settings')) return [crumbSeg('Settings')];
    if (path.startsWith('/studio/project/')) {
        const leaf = path.split('/').pop();
        const label = seg(leaf) || 'Project';
        // The workflow page nests deeper than the board — lead with a "Project"
        // segment so it reads Project → {name} → Workflow.
        if (leaf === 'workflow') {
            return [crumbSeg('Project', true), <Chev key="c0" />, crumbSeg(activeProjectName || 'Project', true), <Chev key="c" />, crumbSeg(label)];
        }
        return [crumbSeg('Home', true), <Chev key="c0" />, crumbSeg(activeProjectName || 'Project', true), <Chev key="c" />, crumbSeg(label)];
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

const liveDot = (n) => (
    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span style={{ position: 'relative', display: 'inline-flex' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--pulse-blue)' }} />
            <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--pulse-blue)', animation: 'livedot 1.8s ease-out infinite' }} />
        </span>
        <span style={{ fontSize: '10px', color: 'var(--pulse-blue)', fontWeight: 600 }}>{n}</span>
    </span>
);

const NEW_ITEMS = [
    { kind: 'task', title: 'Task', sub: 'File work on the board', tint: 'rgba(128,203,196,.14)', stroke: 'var(--brand-teal)', icon: <><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 3v18" /></> },
    { kind: 'project', title: 'Project', sub: 'Guided 5-step wizard', tint: 'rgba(201,184,255,.14)', stroke: 'var(--brand-lavender)', icon: <path d="M3 7v13h18V7M3 7l2-3h14l2 3M3 7h18" /> },
    { kind: 'epic', title: 'Epic', sub: 'Group tasks on the roadmap', tint: 'rgba(197,138,249,.14)', stroke: '#c58af9', icon: <><rect x="3" y="4" width="18" height="6" rx="1" /><rect x="3" y="14" width="18" height="6" rx="1" /></> },
    { kind: 'milestone', title: 'Milestone', sub: 'A date the team is aiming at', tint: 'rgba(251,191,36,.14)', stroke: '#fbbf24', icon: <><path d="M4 22V4" /><path d="M4 4h13l-2 4 2 4H4" /></> },
    { divider: true },
    { kind: 'agent', title: 'Agent', sub: 'Add an AI teammate', tint: 'rgba(56,189,248,.14)', stroke: 'var(--pulse-blue)', icon: <><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /></> },
];

const SWITCH_BTN = (on) => ({
    padding: '5px 14px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '12.5px', fontWeight: 600, fontFamily: 'inherit',
    background: on ? 'var(--surface-card)' : 'transparent', color: on ? 'var(--text-primary)' : 'var(--text-muted)',
    boxShadow: on ? '0 1px 3px rgba(0,0,0,.25)' : 'none',
});

export function AppTopbar({ isBuild = false, onNewProject, onMenu }) {
    const navigate = useNavigate();
    const location = useLocation();
    const { user } = useAuth();
    const { projectId: urlProjectId } = useParams();
    const storedProjectId = useCurrentProjectId();
    const { projects, runningByProject, runningTotal, pulseOpen, togglePulse, recentNotifs: notifs, markNotifRead } = useShellData();
    const activeProjectId = urlProjectId || storedProjectId;
    const activeProject = projects.find((p) => p.id === activeProjectId) || projects[0] || null;
    const crumb = useBreadcrumb(activeProject?.name);

    const [projMenuOpen, setProjMenuOpen] = useState(false);
    const [newOpen, setNewOpen] = useState(false);
    const [bellOpen, setBellOpen] = useState(false);
    const [userOpen, setUserOpen] = useState(false);
    const projRef = useRef(null);
    const newRef = useRef(null);
    const bellRef = useRef(null);
    const userRef = useRef(null);

    const unread = notifs.filter((n) => !n.read).length;
    const activeLive = activeProject ? runningByProject[activeProject.id] || 0 : 0;

    useEffect(() => {
        const onDown = (e) => {
            if (projRef.current && !projRef.current.contains(e.target)) setProjMenuOpen(false);
            if (newRef.current && !newRef.current.contains(e.target)) setNewOpen(false);
            if (bellRef.current && !bellRef.current.contains(e.target)) setBellOpen(false);
            if (userRef.current && !userRef.current.contains(e.target)) setUserOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, []);

    const selectProject = (p) => {
        setCurrentProjectId(p.id);
        setProjMenuOpen(false);
        navigate(`/studio/project/${p.id}/board`);
    };

    const onNotifClick = async (n) => {
        try {
            if (!n.read) {
                await api.markNotificationRead(n.id);
                markNotifRead(n.id);
            }
            if (n.link) navigate(n.link);
        } finally {
            setBellOpen(false);
        }
    };

    const inProject = location.pathname.startsWith('/studio/project/');
    const userName = user?.display_name || user?.name || 'User';

    // Opens the existing create flows. Task/epic modals live in ProjectLayout,
    // milestones in the roadmap, agents in the agents page: when that page is
    // not mounted yet we navigate there and pass the intent via route state.
    const startCreate = (kind) => {
        setNewOpen(false);
        if (kind === 'project') { onNewProject && onNewProject(); return; }
        if (kind === 'agent') { navigate('/forge/agents', { state: { create: 'agent' } }); return; }
        if (!activeProject) return;
        if (kind === 'milestone') { navigate(`/studio/project/${activeProject.id}/roadmap`, { state: { create: 'milestone' } }); return; }
        const listening = inProject || (kind === 'task' && location.pathname.startsWith('/studio/tasks/'));
        if (listening) window.dispatchEvent(new CustomEvent(`open-create-${kind}`));
        else navigate(`/studio/project/${activeProject.id}/board`, { state: { create: kind } });
    };

    const createItem = (tint, stroke, icon, title, sub, onClick) => (
        <div className="nav" onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '9px 10px', borderRadius: '11px', cursor: 'pointer', color: 'inherit' }}>
            <span style={{ width: '30px', height: '30px', borderRadius: '9px', background: tint, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2">{icon}</svg>
            </span>
            <div>
                <div style={{ fontSize: '12.5px', fontWeight: 600 }}>{title}</div>
                <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{sub}</div>
            </div>
        </div>
    );

    return (
        <header style={{ flexShrink: 0, height: '40px', display: 'flex', alignItems: 'center', gap: '12px', padding: '0 6px 0 2px', fontFamily: 'var(--font-sans)', WebkitFontSmoothing: 'antialiased' }}>
            {/* Hamburger — opens the off-canvas rail. CSS hides it on desktop. */}
            {isBuild && <button onClick={onMenu} className="shell-hamburger" title="Menu" aria-label="Open navigation"
                style={{ background: 'none', border: 'none', padding: '6px', color: 'var(--text-tertiary)', cursor: 'pointer', alignItems: 'center', flexShrink: 0 }}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
            </button>}

            {/* Logo lockup — separate from any card, always visible. */}
            <div onClick={() => navigate('/studio')} style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', flexShrink: 0 }}>
                <span style={{ width: '30px', height: '30px', borderRadius: '9px', background: 'linear-gradient(135deg,var(--brand-lavender),var(--brand-teal))', color: 'var(--surface-base)', fontSize: '15px', fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 2px 10px rgba(201,184,255,.35)' }}>A</span>
                <div className="shell-hide-sm" style={{ lineHeight: 1.05 }}>
                    <div style={{ fontSize: '13.5px', fontWeight: 700 }}>Agentira</div>
                </div>
            </div>

            {/* Work | Build — the two areas of the app. */}
            <div role="group" aria-label="Area" style={{ display: 'flex', gap: '2px', padding: '3px', borderRadius: '11px', background: 'var(--overlay-tint-soft)', border: '1px solid var(--overlay-line)', flexShrink: 0 }}>
                <button onClick={() => navigate('/studio')} aria-pressed={!isBuild} style={SWITCH_BTN(!isBuild)}>Work</button>
                <button onClick={() => navigate('/forge')} aria-pressed={isBuild} style={SWITCH_BTN(isBuild)}>Build</button>
            </div>

            {/* Project switcher — only inside a project. */}
            {inProject && <span className="shell-hide-sm" style={{ width: '1px', height: '20px', background: 'var(--overlay-line)', flexShrink: 0 }} />}
            {inProject && <div className="shell-hide-sm" style={{ display: 'flex', alignItems: 'center', gap: '9px', flexShrink: 0 }}>
                <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '.12em', color: 'var(--text-muted)', flexShrink: 0 }}>PROJECT</span>
                <div style={{ position: 'relative', flexShrink: 0 }} ref={projRef}>
                    <div className="hoverline" onClick={() => setProjMenuOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', borderRadius: '10px', cursor: 'pointer', background: 'var(--overlay-tint-soft)', border: '1px solid var(--overlay-line)' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', flexShrink: 0, background: activeProject ? 'var(--accent-primary)' : 'var(--text-muted)' }} />
                        <span style={{ fontSize: '13px', fontWeight: 600, color: activeProject ? 'var(--text-primary)' : 'var(--text-muted)' }}>{activeProject ? activeProject.name : 'No project'}</span>
                        {activeLive > 0 ? liveDot(activeLive) : null}
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" style={{ stroke: 'var(--text-muted)', marginLeft: '1px' }}><path d="M8 9l4-4 4 4" /><path d="M16 15l-4 4-4-4" /></svg>
                    </div>
                    {projMenuOpen && (
                        <div style={{ position: 'absolute', top: '100%', left: 0, marginTop: '6px', width: '264px', background: 'var(--surface-card)', border: '1px solid var(--overlay-line)', borderRadius: '14px', boxShadow: 'var(--shadow-popover)', zIndex: 50, padding: '5px', maxHeight: '340px', overflowY: 'auto' }}>
                            <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '.1em', color: 'var(--text-muted)', padding: '6px 8px 4px' }}>SWITCH PROJECT</div>
                            {projects.map((p) => {
                                const live = runningByProject[p.id] || 0;
                                return (
                                    <div key={p.id} className="nav" onClick={() => selectProject(p)} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '7px 8px', borderRadius: '10px', cursor: 'pointer' }}>
                                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', flexShrink: 0, background: 'var(--accent-primary)' }} />
                                        <span style={{ fontSize: '13px', flex: 1, color: 'var(--text-bright)' }}>{p.name}</span>
                                        {live > 0 ? <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--pulse-blue)' }} /><span style={{ fontSize: '10px', color: 'var(--pulse-blue)', fontWeight: 600 }}>{live}</span></span> : null}
                                        {activeProject && p.id === activeProject.id ? <svg className="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ stroke: 'var(--brand-lavender)' }} strokeWidth="2.4"><path d="M20 6 9 17l-5-5" /></svg> : null}
                                    </div>
                                );
                            })}
                            <div className="nav" onClick={() => { setProjMenuOpen(false); onNewProject && onNewProject(); }} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '7px 8px', borderRadius: '10px', cursor: 'pointer', color: 'var(--text-muted)', borderTop: '1px solid var(--overlay-tint)', marginTop: '4px' }}>
                                <svg className="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
                                <span style={{ fontSize: '12.5px' }}>New project</span>
                            </div>
                        </div>
                    )}
                </div>
            </div>}

            {/* Breadcrumb */}
            <div className="shell-hide-sm" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', minWidth: 0, flex: 1 }}>{crumb}</div>
            <div className="shell-spacer-sm" />

            <div className="shell-hide-sm"><GlobalSearch /></div>

            {/* Right controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '9px' }}>
                {/* Pulse pill — toggles the full-height Pulse drawer (PulseDock).
                    Pulse blue when something is running; muted "All quiet" otherwise.
                    Always clickable so the drawer can be pulled out / dismissed. */}
                {isBuild && <div
                    onClick={togglePulse}
                    title={pulseOpen ? 'Hide Pulse' : 'Show Pulse'}
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px', borderRadius: '999px', background: runningTotal > 0 ? 'rgba(56,189,248,.08)' : (pulseOpen ? 'var(--overlay-tint)' : 'transparent'), border: `1px solid ${runningTotal > 0 ? 'rgba(56,189,248,.3)' : 'var(--overlay-line)'}`, cursor: 'pointer' }}
                >
                    {runningTotal > 0 ? (
                        <>
                            <span style={{ position: 'relative', display: 'inline-flex' }}>
                                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--pulse-blue)' }} />
                                <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--pulse-blue)', animation: 'livedot 1.8s ease-out infinite' }} />
                            </span>
                            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--pulse-blue)' }}>{runningTotal} running</span>
                        </>
                    ) : (
                        <>
                            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--text-muted)' }} />
                            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)' }}>Live status</span>
                        </>
                    )}
                </div>}

                {/* New menu */}
                <div style={{ position: 'relative' }} ref={newRef}>
                    <div onClick={() => setNewOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '7px 13px', borderRadius: '10px', background: 'var(--brand-lavender)', color: 'var(--accent-on)', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}>
                        <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 5v14M5 12h14" /></svg>New
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M6 9l6 6 6-6" /></svg>
                    </div>
                    {newOpen && (
                        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '250px', background: 'var(--surface-card)', border: '1px solid var(--overlay-line)', borderRadius: '14px', boxShadow: 'var(--shadow-popover)', zIndex: 50, padding: '6px' }}>
                            {NEW_ITEMS.map((it) => it.divider
                                ? <div key="div" style={{ height: '1px', background: 'var(--overlay-tint)', margin: '5px 4px' }} />
                                : <React.Fragment key={it.kind}>{createItem(it.tint, it.stroke, it.icon, it.title, it.sub, () => startCreate(it.kind))}</React.Fragment>)}
                        </div>
                    )}
                </div>

                {/* Bell */}
                <div className="shell-hide-sm" style={{ position: 'relative' }} ref={bellRef}>
                    <div className="hovertint" onClick={() => setBellOpen((o) => !o)} style={{ position: 'relative', padding: '7px', color: 'var(--text-tertiary)', cursor: 'pointer', borderRadius: '9px' }}>
                        <svg className="ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>
                        {unread > 0 && <span style={{ position: 'absolute', top: '4px', right: '4px', width: '7px', height: '7px', borderRadius: '50%', background: '#ef4444', border: '2px solid var(--canvas-base)' }} />}
                    </div>
                    {bellOpen && (
                        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '312px', background: 'var(--surface-card)', border: '1px solid var(--overlay-line)', borderRadius: '14px', boxShadow: 'var(--shadow-popover)', zIndex: 50, overflow: 'hidden' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '11px 14px', borderBottom: '1px solid var(--overlay-tint)' }}>
                                <span style={{ fontSize: '12.5px', fontWeight: 700 }}>Notifications</span>
                                {unread > 0 && <span style={{ fontSize: '11px', fontWeight: 700, background: '#ef4444', color: '#fff', borderRadius: '999px', padding: '1px 7px' }}>{unread}</span>}
                            </div>
                            <div style={{ padding: '5px', maxHeight: '320px', overflowY: 'auto' }}>
                                {notifs.length === 0 ? (
                                    <div style={{ padding: '24px 8px', textAlign: 'center', fontSize: '12px', color: 'var(--text-muted)' }}>You're all caught up.</div>
                                ) : notifs.slice(0, 8).map((n) => (
                                    <div key={n.id} className="nav" onClick={() => onNotifClick(n)} style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '9px', borderRadius: '11px', cursor: 'pointer', opacity: n.read ? 0.6 : 1 }}>
                                        <span style={{ marginTop: '1px', width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0, background: n.read ? 'transparent' : '#ef4444' }} />
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            {isRunMeta(n.meta)
                                                ? <RunNotificationLine meta={n.meta} />
                                                : <div style={{ fontSize: '12.5px', color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title}</div>}
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{isRunMeta(n.meta) ? n.meta.project_name : n.type}{n.created_at ? ` · ${new Date(n.created_at).toLocaleString()}` : ''}</div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div className="nav" onClick={() => { setBellOpen(false); navigate('/studio'); }} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '10px', borderTop: '1px solid var(--overlay-tint)', fontSize: '12px', fontWeight: 600, color: 'var(--brand-lavender)', cursor: 'pointer' }}>
                                Open Inbox<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                            </div>
                        </div>
                    )}
                </div>

                {/* Avatar — account menu; Inbox / My Work / Chat live here now that Work has no sidebar. */}
                <div style={{ position: 'relative' }} ref={userRef}>
                    <div title={userName} onClick={() => setUserOpen((o) => !o)} style={{ position: 'relative', width: '30px', height: '30px', borderRadius: '50%', background: 'rgba(201,184,255,.12)', color: 'var(--brand-lavender)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}>
                        {userName[0].toUpperCase()}
                        {unread > 0 && <span style={{ position: 'absolute', top: '-1px', right: '-1px', width: '8px', height: '8px', borderRadius: '50%', background: '#ef4444', border: '2px solid var(--canvas-base)' }} />}
                    </div>
                    {userOpen && (
                        <div className="usermenu" style={{ position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '210px', background: 'var(--surface-card)', border: '1px solid var(--overlay-line)', borderRadius: '14px', boxShadow: 'var(--shadow-popover)', zIndex: 60, padding: '5px' }}>
                            <div style={{ padding: '8px 10px 6px', lineHeight: 1.2 }}>
                                <div style={{ fontSize: '12.5px', fontWeight: 600 }}>{userName}</div>
                                <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{user?.role || 'member'}</div>
                            </div>
                            {[['Inbox', '/studio/inbox', unread], ['My Work', '/studio/my-work', 0], ['Chat', '/chat', 0], ['Settings', '/studio/settings', 0]].map(([label, to, n]) => (
                                <div key={label} className="nav" onClick={() => { setUserOpen(false); navigate(to); }} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', borderRadius: '10px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-tertiary)' }}>
                                    <span style={{ flex: 1 }}>{label}</span>
                                    {n > 0 && <span style={{ fontSize: '10px', fontWeight: 700, background: '#ef4444', color: '#fff', borderRadius: '999px', padding: '1px 6px' }}>{n}</span>}
                                </div>
                            ))}
                            <div className="nav" onClick={() => { localStorage.removeItem('agentira_token'); navigate('/login'); }} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', borderRadius: '10px', cursor: 'pointer', fontSize: '13px', color: '#f87171' }}>Sign out</div>
                        </div>
                    )}
                </div>
            </div>
        </header>
    );
}
