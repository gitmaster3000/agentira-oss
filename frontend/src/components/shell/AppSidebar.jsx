import React, { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useCurrentProjectId, setCurrentProjectId } from '../../currentProject';
import { useShellData, projectColor } from './shellData';

// Exact port of Agentira.dc.html sidebar (design hash RjjZ09618cpj5TzJmourRQ):
// inline styles + SVG paths copied verbatim so the chrome is pixel-identical.
// All data is real — projects, user, running-run counts, agent count,
// unread notifications come from api.js, not the prototype's mock rows.

// navStyle from the prototype's support.js (lines 1537-1538) — verbatim.
const navStyle = (active) => ({
    display: 'flex', alignItems: 'center', gap: '11px', padding: '8px 10px',
    borderRadius: '9px', cursor: 'pointer', fontSize: '13px', transition: 'background .12s',
    ...(active
        ? { background: 'rgba(201,184,255,.10)', color: '#c9b8ff', fontWeight: 600 }
        : { color: '#b1bac4' }),
});

const grayBadge = (n) => <span style={{ fontSize: '10px', color: '#768390' }}>{n}</span>;

const liveDot = (n) => (
    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span style={{ position: 'relative', display: 'inline-flex' }}>
            <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#38bdf8' }} />
            <span style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: '#38bdf8', animation: 'livedot 1.8s ease-out infinite' }} />
        </span>
        <span style={{ fontSize: '10px', color: '#38bdf8', fontWeight: 600 }}>{n}</span>
    </span>
);

function NavRow({ active, onClick, icon, label, badge }) {
    return (
        <div className="nav" onClick={onClick} style={navStyle(active)}>
            {icon}
            <span style={{ flex: 1 }}>{label}</span>
            {badge}
        </div>
    );
}

export function AppSidebar() {
    const navigate = useNavigate();
    const location = useLocation();
    const { projectId: urlProjectId } = useParams();
    const storedProjectId = useCurrentProjectId();
    const { user } = useAuth();
    const { projects, runningByProject, runningTotal, agentCount, unread } = useShellData();

    const path = location.pathname;
    const [projMenuOpen, setProjMenuOpen] = useState(false);
    const [userOpen, setUserOpen] = useState(false);
    const projRef = useRef(null);
    const userRef = useRef(null);

    useEffect(() => {
        const onDown = (e) => {
            if (projRef.current && !projRef.current.contains(e.target)) setProjMenuOpen(false);
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
        projSettings: path.includes('/project/') && path.includes('/settings'),
    };

    const selectProject = (p) => {
        setCurrentProjectId(p.id);
        setProjMenuOpen(false);
        navigate(`/studio/project/${p.id}/board`);
    };

    const userInitial = (user?.display_name || user?.name || 'U')[0].toUpperCase();
    const activeLive = active ? runningByProject[active.id] || 0 : 0;

    return (
        <aside style={{ width: '248px', flexShrink: 0, borderRight: '1px solid #30363d', background: '#161b22', display: 'flex', flexDirection: 'column', fontFamily: 'var(--font-sans)', WebkitFontSmoothing: 'antialiased' }}>
            {/* workspace — fixed 54px to align its bottom border with the topbar's */}
            <div style={{ height: '54px', flexShrink: 0, padding: '0 12px', borderBottom: '1px solid #30363d', display: 'flex', alignItems: 'center' }}>
                <div onClick={() => navigate('/studio')} style={{ display: 'flex', alignItems: 'center', gap: '9px', width: '100%', padding: '7px 8px', borderRadius: '10px', background: '#1c2128', border: '1px solid #30363d', cursor: 'pointer' }}>
                    <span style={{ width: '26px', height: '26px', borderRadius: '7px', background: 'linear-gradient(135deg,#c9b8ff,#80cbc4)', color: '#0e1117', fontSize: '13px', fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>A</span>
                    <div style={{ flex: 1, lineHeight: 1.1 }}>
                        <div style={{ fontSize: '13px', fontWeight: 600 }}>Agentira</div>
                        <div style={{ fontSize: '10px', color: '#768390' }}>Workspace</div>
                    </div>
                </div>
            </div>

            {/* search */}
            <div style={{ padding: '10px 12px 4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 10px', borderRadius: '10px', background: '#0e1117', border: '1px solid #30363d', color: '#768390', cursor: 'text' }}>
                    <svg className="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
                    <span style={{ fontSize: '12.5px', flex: 1 }}>Search or jump…</span>
                    <span style={{ fontSize: '10px', fontFamily: 'ui-monospace,monospace', background: '#1c2128', border: '1px solid #30363d', borderRadius: '5px', padding: '2px 5px', color: '#b1bac4' }}>⌘K</span>
                </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }}>
                {/* global */}
                <NavRow active={is.home} onClick={() => navigate('/studio')} label="Home"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M9 22V12h6v10" /></svg>} />
                <NavRow active={false} onClick={() => navigate('/studio')} label="Inbox"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /></svg>}
                    badge={unread > 0 ? <span style={{ fontSize: '10px', fontWeight: 700, background: '#ef4444', color: '#fff', borderRadius: '999px', padding: '1px 6px' }}>{unread}</span> : null} />
                <NavRow active={false} onClick={() => navigate('/studio')} label="My Work"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>} />
                <NavRow active={is.chat} onClick={() => navigate('/chat')} label="Chat"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>} />

                {/* BUILD */}
                <div style={{ padding: '16px 10px 7px', fontSize: '11.5px', fontWeight: 800, letterSpacing: '.14em', color: '#aeb6c0' }}>BUILD</div>
                <NavRow active={is.agents} onClick={() => navigate('/forge/agents')} label="Agents"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /><line x1="8" y1="16" x2="8" y2="16" /><line x1="16" y1="16" x2="16" y2="16" /></svg>}
                    badge={agentCount != null ? grayBadge(agentCount) : null} />
                <NavRow active={is.runs} onClick={() => navigate('/forge/runs')} label="Runs"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3" /></svg>}
                    badge={runningTotal > 0 ? liveDot(runningTotal) : null} />
                <NavRow active={is.conductor} onClick={() => navigate('/forge/conductor')} label="Conductor"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="2" /><path d="M4.93 19.07a10 10 0 0 1 0-14.14M7.76 16.24a6 6 0 0 1 0-8.48M16.24 7.76a6 6 0 0 1 0 8.48M19.07 4.93a10 10 0 0 1 0 14.14" /></svg>} />
                <NavRow active={is.runtimes} onClick={() => navigate('/forge/runtimes')} label="Runtimes"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /></svg>} />
                <NavRow active={is.mcp} onClick={() => navigate('/forge/settings')} label="MCP Servers"
                    icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" /><line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" /></svg>} />

                {/* PROJECT */}
                <div style={{ padding: '16px 10px 7px', fontSize: '11.5px', fontWeight: 800, letterSpacing: '.14em', color: '#aeb6c0' }}>PROJECT</div>
                <div style={{ position: 'relative' }} ref={projRef}>
                    <div onClick={() => setProjMenuOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '9px 10px', borderRadius: '9px', cursor: 'pointer', background: '#1c2128', border: '1px solid #30363d' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', flexShrink: 0, background: active ? projectColor(active) : '#768390' }} />
                        <span style={{ fontSize: '13px', fontWeight: 600, flex: 1, color: active ? projectColor(active) : '#768390' }}>{active ? active.name : 'No project'}</span>
                        {activeLive > 0 ? liveDot(activeLive) : null}
                        <svg className="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#768390" strokeWidth="2"><path d="M6 9l6 6 6-6" /></svg>
                    </div>
                    {projMenuOpen && (
                        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: '4px', background: '#1c2128', border: '1px solid #30363d', borderRadius: '10px', boxShadow: '0 12px 32px rgba(0,0,0,.5)', zIndex: 40, padding: '5px', maxHeight: '320px', overflowY: 'auto' }}>
                            <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '.1em', color: '#768390', padding: '6px 8px 4px' }}>SWITCH PROJECT</div>
                            {projects.map((p) => {
                                const live = runningByProject[p.id] || 0;
                                return (
                                    <div key={p.id} className="nav" onClick={() => selectProject(p)} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '7px 8px', borderRadius: '7px', cursor: 'pointer' }}>
                                        <span style={{ width: '8px', height: '8px', borderRadius: '2px', flexShrink: 0, background: projectColor(p) }} />
                                        <span style={{ fontSize: '13px', flex: 1, color: '#e8ebf0' }}>{p.name}</span>
                                        {live > 0 ? <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#38bdf8' }} /><span style={{ fontSize: '10px', color: '#38bdf8', fontWeight: 600 }}>{live}</span></span> : null}
                                        {p.id === (active && active.id) ? <svg className="ico" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#c9b8ff" strokeWidth="2.4"><path d="M20 6 9 17l-5-5" /></svg> : null}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* plan nav */}
                <div style={{ padding: '8px 4px 0' }}>
                    <NavRow active={is.overview} onClick={() => navigate(projPath('overview'))} label="Overview"
                        icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z" /></svg>} />
                    <NavRow active={is.board} onClick={() => navigate(projPath('board'))} label="Board"
                        icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="18" rx="1" /><rect x="14" y="3" width="7" height="9" rx="1" /></svg>} />
                    <NavRow active={is.backlog} onClick={() => navigate(projPath('backlog'))} label="Backlog"
                        icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></svg>} />
                    <NavRow active={is.roadmap} onClick={() => navigate(projPath('roadmap'))} label="Roadmap"
                        icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18" /><path d="m7 14 4-4 3 3 5-6" /></svg>} />
                    <NavRow active={false} onClick={() => navigate(projPath('settings'))} label="Workflow"
                        icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="6" height="6" rx="1" /><rect x="15" y="3" width="6" height="6" rx="1" /><rect x="9" y="15" width="6" height="6" rx="1" /><path d="M6 9v3a2 2 0 0 0 2 2h4M18 9v3a2 2 0 0 1-2 2h-1" /></svg>} />
                    <NavRow active={is.projSettings} onClick={() => navigate(projPath('settings'))} label="Settings"
                        icon={<svg className="ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /><path d="M12 1v4M12 19v4M4.2 4.2l2.8 2.8M17 17l2.8 2.8M1 12h4M19 12h4M4.2 19.8 7 17M17 7l2.8-2.8" /></svg>} />
                </div>
            </div>

            {/* footer user */}
            <div style={{ borderTop: '1px solid #30363d', padding: '8px', position: 'relative' }} ref={userRef}>
                <div className="nav" onClick={() => setUserOpen((o) => !o)} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '7px 9px', borderRadius: '8px', cursor: 'pointer' }}>
                    <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: 'rgba(201,184,255,.12)', color: '#c9b8ff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 600 }}>{userInitial}</div>
                    <div style={{ flex: 1, lineHeight: 1.15 }}>
                        <div style={{ fontSize: '12px', fontWeight: 500 }}>{user?.display_name || user?.name || 'User'}</div>
                        <div style={{ fontSize: '10px', color: '#768390' }}>{user?.role || 'member'}</div>
                    </div>
                    <svg className="ico" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#768390" strokeWidth="2"><path d="M8 9l4-4 4 4" /><path d="M16 15l-4 4-4-4" /></svg>
                </div>
                {userOpen && (
                    <div style={{ position: 'absolute', bottom: '100%', left: '8px', right: '8px', marginBottom: '4px', background: '#1c2128', border: '1px solid #30363d', borderRadius: '10px', boxShadow: '0 12px 32px rgba(0,0,0,.5)', zIndex: 40, padding: '5px' }}>
                        <div className="nav" onClick={() => { setUserOpen(false); navigate('/studio/settings'); }} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '8px', borderRadius: '7px', cursor: 'pointer', fontSize: '13px', color: '#b1bac4' }}>
                            <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /><path d="M12 1v4M12 19v4M1 12h4M19 12h4" /></svg>Settings
                        </div>
                        <div className="nav" onClick={() => { localStorage.removeItem('agentira_token'); navigate('/login'); }} style={{ display: 'flex', alignItems: 'center', gap: '9px', padding: '8px', borderRadius: '7px', cursor: 'pointer', fontSize: '13px', color: '#f87171' }}>
                            <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>Sign out
                        </div>
                    </div>
                )}
            </div>
        </aside>
    );
}
