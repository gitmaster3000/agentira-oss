import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useCurrentProjectId } from '../../currentProject';
import { useShellData } from './shellData';

// Exact port of the Agentira.dc.html collapsible icon rail: a floating panel
// (radius 16, hairline border, soft shadow) that animates between 248px and
// 66px. Collapsing is driven by the `.rc` class on both `.railwrap` and
// `.rail` — the width, the `.rl` label hiding, the centred nav rows, the
// section-header dividers and the user-menu flyout all live in shell.css.
//
// All data is real — projects, user, running-run counts, agent count and
// unread notifications come from api.js, not the prototype's mock rows.

// navStyle from the prototype's support.js — verbatim.
const navStyle = (active) => ({
    display: 'flex', alignItems: 'center', gap: '11px', padding: '8px 10px',
    borderRadius: '9px', cursor: 'pointer', fontSize: '13px', transition: 'background .12s',
    ...(active
        ? { background: 'rgba(201,184,255,.10)', color: 'var(--brand-lavender)', fontWeight: 600 }
        : { color: 'var(--text-tertiary)' }),
});

const grayBadge = (n) => <span className="rl" style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{n}</span>;

const liveDot = (n) => (
    <span className="rl" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span style={{ position: 'relative', display: 'inline-flex' }}>
            <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: 'var(--pulse-blue)' }} />
            <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: 'var(--pulse-blue)', animation: 'livedot 1.8s ease-out infinite' }} />
        </span>
        <span style={{ fontSize: '10px', color: 'var(--pulse-blue)', fontWeight: 600 }}>{n}</span>
    </span>
);

// `title` gives the collapsed rail its native tooltip; `.rl` marks the parts
// that disappear when the rail collapses to icons.
function NavRow({ active, onClick, icon, label, badge }) {
    return (
        <div className="nav" title={label} onClick={onClick} style={navStyle(active)}>
            {icon}
            <span className="rl" style={{ flex: 1 }}>{label}</span>
            {badge}
        </div>
    );
}

// Expanded: a text section header. Collapsed: a border-top divider + dimmed icon.
function RailHeader({ label, icon }) {
    return (
        <div className="railhdr" style={{ padding: '16px 10px 7px', fontSize: '11.5px', fontWeight: 800, letterSpacing: '.14em', color: 'var(--text-section)' }}>
            {icon}
            <span className="hdrlabel">{label}</span>
        </div>
    );
}

const buildIcon = (
    <svg className="hdricon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6b7280" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="m14.5 5.5 4 4L21 7a5 5 0 0 1-6.9 6.9l-6.6 6.6a2.1 2.1 0 0 1-3-3l6.6-6.6A5 5 0 0 1 18 4z" /></svg>
);
const projectIcon = (
    <svg className="hdricon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6b7280" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>
);

export function AppSidebar({ open = false, railOpen = true, onToggleRail }) {
    const navigate = useNavigate();
    const location = useLocation();
    const { projectId: urlProjectId } = useParams();
    const storedProjectId = useCurrentProjectId();
    const { user } = useAuth();
    const { projects, runningTotal, agentCount, unread } = useShellData();

    const path = location.pathname;
    const [userOpen, setUserOpen] = useState(false);
    const userRef = useRef(null);

    useEffect(() => {
        const onDown = (e) => {
            if (userRef.current && !userRef.current.contains(e.target)) setUserOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        return () => document.removeEventListener('mousedown', onDown);
    }, []);

    const activeProjectId = urlProjectId || storedProjectId;
    const active = projects.find((p) => p.id === activeProjectId) || projects[0] || null;
    const projPath = (leaf) => (active ? `/studio/project/${active.id}/${leaf}` : '/studio');

    const is = {
        home: path === '/studio',
        inbox: path === '/studio/inbox',
        mywork: path === '/studio/my-work',
        chat: path === '/chat',
        agents: path.startsWith('/forge/agents'),
        runs: path.startsWith('/forge/runs'),
        conductor: path.startsWith('/forge/conductor'),
        runtimes: path.startsWith('/forge/runtimes'),
        mcp: path === '/forge/settings',
        overview: path.includes('/overview'),
        board: path.includes('/board') || path.startsWith('/studio/tasks/'),
        backlog: path.includes('/backlog'),
        roadmap: path.includes('/roadmap'),
        workflow: path.includes('/workflow'),
        deploy: path.includes('/deploy'),
        projSettings: path.includes('/project/') && path.includes('/settings'),
    };

    const userInitial = (user?.display_name || user?.name || 'U')[0].toUpperCase();
    const rc = railOpen ? '' : ' rc';

    return (
        <aside
            className={`railwrap shell-sidebar${rc}${open ? ' shell-sidebar--open' : ''}`}
            style={{ flexShrink: 0, position: 'relative', zIndex: 30, fontFamily: 'var(--font-sans)', WebkitFontSmoothing: 'antialiased' }}
        >
            <div className={`rail${rc}`} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', flexDirection: 'column', background: 'var(--surface-raised)', border: '1px solid var(--overlay-tint)', borderRadius: '16px', boxShadow: 'var(--shadow-panel)' }}>
                {/* collapse toggle (top of the rail) */}
                <div className="railtoggle-wrap" style={{ position: 'relative', zIndex: 1, display: 'flex', justifyContent: 'flex-end', padding: '10px 12px 2px' }}>
                    <div className="hovertint" onClick={onToggleRail} title="Toggle sidebar" style={{ width: '30px', height: '30px', flexShrink: 0, borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: 'var(--text-tertiary)', border: '1px solid var(--overlay-line)' }}>
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="9" y1="4" x2="9" y2="20" /></svg>
                    </div>
                </div>

                <div style={{ position: 'relative', zIndex: 1, flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '6px 8px' }}>
                    {/* global */}
                    <NavRow active={is.home} onClick={() => navigate('/studio')} label="Home"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M9 22V12h6v10" /></svg>} />
                    <NavRow active={is.inbox} onClick={() => navigate('/studio/inbox')} label="Inbox"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></svg>}
                        badge={unread > 0 ? <span className="rl" style={{ fontSize: '10px', fontWeight: 700, background: '#ef4444', color: '#fff', borderRadius: '999px', padding: '1px 6px' }}>{unread}</span> : null} />
                    <NavRow active={is.mywork} onClick={() => navigate('/studio/my-work')} label="My Work"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>} />
                    <NavRow active={is.chat} onClick={() => navigate('/chat')} label="Chat"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>} />

                    {/* BUILD */}
                    <RailHeader label="BUILD" icon={buildIcon} />
                    <NavRow active={is.agents} onClick={() => navigate('/forge/agents')} label="Agents"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /><line x1="8" y1="16" x2="8" y2="16" /><line x1="16" y1="16" x2="16" y2="16" /></svg>}
                        badge={agentCount != null ? grayBadge(agentCount) : null} />
                    <NavRow active={is.runs} onClick={() => navigate('/forge/runs')} label="Runs"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3" /></svg>}
                        badge={runningTotal > 0 ? liveDot(runningTotal) : null} />
                    <NavRow active={is.conductor} onClick={() => navigate('/forge/conductor')} label="Conductor"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="2" /><path d="M4.93 19.07a10 10 0 0 1 0-14.14M7.76 16.24a6 6 0 0 1 0-8.48M16.24 7.76a6 6 0 0 1 0 8.48M19.07 4.93a10 10 0 0 1 0 14.14" /></svg>} />
                    <NavRow active={is.runtimes} onClick={() => navigate('/forge/runtimes')} label="Agent Runtimes"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /></svg>} />
                    <NavRow active={is.mcp} onClick={() => navigate('/forge/settings')} label="MCP Servers"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" /><line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" /></svg>} />

                    {/* PROJECT — the switcher itself now lives in the top bar. */}
                    <RailHeader label="PROJECT" icon={projectIcon} />
                    <div className="plangroup" style={{ margin: '8px 2px 0 9px', padding: '7px 0 2px' }}>
                        <NavRow active={is.overview} onClick={() => navigate(projPath('overview'))} label="Overview"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z" /></svg>} />
                        <NavRow active={is.board} onClick={() => navigate(projPath('board'))} label="Board"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="9" rx="1" /></svg>} />
                        <NavRow active={is.backlog} onClick={() => navigate(projPath('backlog'))} label="Backlog"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></svg>} />
                        <NavRow active={is.roadmap} onClick={() => navigate(projPath('roadmap'))} label="Roadmap"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18" /><path d="m7 14 4-4 3 3 5-6" /></svg>} />
                        <NavRow active={is.workflow} onClick={() => navigate(projPath('workflow'))} label="Workflow"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="3" width="6" height="6" rx="1" /><rect x="9" y="15" width="6" height="6" rx="1" /><path d="M6 9v3a2 2 0 0 0 2 2h4M18 9v3a2 2 0 0 1-2 2h-1" /></svg>} />
                        {/* Deploy is not in the design's rail, but the route is live — dropping
                            the row would orphan /studio/project/:id/deploy. */}
                        <NavRow active={is.deploy} onClick={() => navigate(projPath('deploy'))} label="Deploy"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>} />
                        <NavRow active={is.projSettings} onClick={() => navigate(projPath('settings'))} label="Settings"
                            icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /><path d="M12 1v4M12 19v4M4.2 4.2l2.8 2.8M17 17l2.8 2.8M1 12h4M19 12h4M4.2 19.8 7 17M17 7l2.8-2.8" /></svg>} />
                    </div>
                </div>

                {/* footer user */}
                <div style={{ position: 'relative', zIndex: 1, borderTop: '1px solid var(--overlay-tint)', padding: '8px' }} ref={userRef}>
                    <div className="nav" title={user?.display_name || user?.name || 'User'} onClick={() => setUserOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '7px 9px', borderRadius: '10px', cursor: 'pointer' }}>
                        <div style={{ width: '28px', height: '28px', flexShrink: 0, borderRadius: '50%', background: 'rgba(201,184,255,.12)', color: 'var(--brand-lavender)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 600 }}>{userInitial}</div>
                        <div className="rl" style={{ flex: 1, lineHeight: 1.15 }}>
                            <div style={{ fontSize: '12px', fontWeight: 500 }}>{user?.display_name || user?.name || 'User'}</div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{user?.role || 'member'}</div>
                        </div>
                        <svg className="ico rl" width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ stroke: 'var(--text-muted)' }} strokeWidth="2"><path d="M8 9l4-4 4 4" /><path d="M16 15l-4 4-4-4" /></svg>
                    </div>
                    {userOpen && (
                        // Opens above when expanded; shell.css flies it out to the right of
                        // the rail when collapsed (.rail.rc .usermenu).
                        <div className="usermenu" style={{ position: 'absolute', bottom: '100%', left: '8px', right: '8px', marginBottom: '6px', background: 'var(--surface-card)', border: '1px solid var(--overlay-line)', borderRadius: '14px', boxShadow: 'var(--shadow-popover)', zIndex: 60, padding: '5px' }}>
                            <div className="nav" onClick={() => { setUserOpen(false); navigate('/studio/settings'); }} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', borderRadius: '10px', cursor: 'pointer', fontSize: '13px', color: 'var(--text-tertiary)' }}>
                                <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /><path d="M12 1v4M12 19v4M1 12h4M19 12h4" /></svg>Settings
                            </div>
                            <div className="nav" onClick={() => { localStorage.removeItem('agentira_token'); navigate('/login'); }} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', borderRadius: '10px', cursor: 'pointer', fontSize: '13px', color: '#f87171' }}>
                                <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>Sign out
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </aside>
    );
}
