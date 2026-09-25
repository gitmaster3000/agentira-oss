import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../../api';

// Projects have no colour of their own. Every project marker uses the one
// brand accent (--accent-primary), which flips with the day/night theme.

export function projectKey(p) {
    if (p?.key) return p.key;
    return (p?.name || '??').replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase() || '??';
}

// One shared fetch for the chrome: projects, running runs (list + per-project and
// total counts), runs waiting on a human, recent notifications, agent count, unread.
// Everything the sidebar, the topbar "N running" pill AND the Pulse drawer need —
// all from the SAME query, mounted once via ShellDataProvider so the pill and the
// drawer are a single source (COMPONENT_MAP key behavior #2: "Pulse is global").
// Also owns the Pulse drawer open/close state so the topbar pill (toggle) and the
// drawer (panel) stay in sync. Polls live data on the 30s ADR-007 cadence.
const ShellDataContext = createContext({
    projects: [], runningRuns: [], runningByProject: {}, runningTotal: 0,
    waitingRuns: [], recentNotifs: [], agentCount: null, unread: 0,
    pulseOpen: false, togglePulse: () => {}, dismissWaiting: () => {},
});

const PULSE_KEY = 'agentira.pulseOpen';

export function ShellDataProvider({ children }) {
    const [projects, setProjects] = useState([]);
    const [runningRuns, setRunningRuns] = useState([]);
    const [runningByProject, setRunningByProject] = useState({});
    const [runningTotal, setRunningTotal] = useState(0);
    const [waitingRuns, setWaitingRuns] = useState([]);
    const [recentNotifs, setRecentNotifs] = useState([]);
    const [agentCount, setAgentCount] = useState(null);
    const [unread, setUnread] = useState(0);
    // Pulse is an on-demand slide-over: opened from the top-bar pill, closed by
    // clicking the backdrop. Starts closed; the user's choice persists across
    // sessions. Guarded — localStorage can throw (private mode / restricted).
    const [pulseOpen, setPulseOpen] = useState(() => {
        try { return localStorage.getItem(PULSE_KEY) === 'true'; } catch { return false; }
    });

    const togglePulse = () => setPulseOpen((o) => {
        const next = !o;
        try { localStorage.setItem(PULSE_KEY, String(next)); } catch { /* ignore */ }
        return next;
    });

    // Drop a "Needs you" question at once; the server keeps it hidden until
    // the agent asks a new one. A failed call just lets the next poll restore it.
    const dismissWaiting = (id) => {
        setWaitingRuns((list) => list.filter((r) => r.id !== id));
        api.forge.dismissRun(id).catch(() => {});
    };

    useEffect(() => {
        let cancelled = false;

        const loadStatic = async () => {
            try {
                const [pj, agents] = await Promise.all([
                    api.getProjects().catch(() => []),
                    api.forge.listAgents().catch(() => []),
                ]);
                if (cancelled) return;
                setProjects(Array.isArray(pj) ? pj : []);
                setAgentCount(Array.isArray(agents) ? agents.length : null);
            } catch { /* ignore */ }
        };

        const loadLive = async () => {
            try {
                const [runs, waiting, notifs] = await Promise.all([
                    api.forge.listRuns({ status: 'running' }).catch(() => []),
                    api.forge.listRuns({ outcome: 'needs_input', unresolved: true }).catch(() => []),
                    api.getNotifications(false).catch(() => []),
                ]);
                if (cancelled) return;
                const list = Array.isArray(runs) ? runs : [];
                const by = {};
                for (const r of list) {
                    const pid = r.project_id;
                    if (pid) by[pid] = (by[pid] || 0) + 1;
                }
                setRunningRuns(list);
                setRunningByProject(by);
                setRunningTotal(list.length);
                setWaitingRuns(Array.isArray(waiting) ? waiting : []);
                const nlist = Array.isArray(notifs) ? notifs : [];
                setRecentNotifs(nlist);
                setUnread(nlist.filter((x) => !x.read).length);
            } catch { /* ignore */ }
        };

        loadStatic();
        loadLive();
        const id = setInterval(loadLive, 30_000);
        return () => { cancelled = true; clearInterval(id); };
    }, []);

    const value = {
        projects, runningRuns, runningByProject, runningTotal,
        waitingRuns, recentNotifs, agentCount, unread,
        pulseOpen, togglePulse, dismissWaiting,
    };
    return <ShellDataContext.Provider value={value}>{children}</ShellDataContext.Provider>;
}

export function useShellData() {
    return useContext(ShellDataContext);
}
