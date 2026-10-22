import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
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

export function AppSidebar({ open = false, railOpen = true, onToggleRail }) {
    const navigate = useNavigate();
    const location = useLocation();
    const { runningTotal, agentCount } = useShellData();

    const path = location.pathname;

    const is = {
        agents: path.startsWith('/forge/agents'),
        runs: path.startsWith('/forge/runs'),
        conductor: path.startsWith('/forge/conductor'),
        runtimes: path.startsWith('/forge/runtimes'),
        mcp: path === '/forge/mcp',
    };

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
                    <NavRow active={is.mcp} onClick={() => navigate('/forge/mcp')} label="MCP Servers"
                        icon={<svg className="ico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" /><line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" /></svg>} />
                </div>

            </div>
        </aside>
    );
}
