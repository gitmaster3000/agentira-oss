import React, { createContext, useContext, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../../api';

// Projects have no colour of their own. Every project marker uses the one
// brand accent (--accent-primary), which flips with the day/night theme.

// AP-509: where a "Needs you" card leads — the agent's task chat, where the
// question is waiting with its answer options; the run page when no task.
export function waitingLink(r) {
    return r.task_id && r.agent_id
        ? `/chat?agent=${r.agent_id}&scope=task:${r.task_id}`
        : `/forge/runs/${r.id}`;
}

export function projectKey(p) {
    if (p?.key) return p.key;
    return (p?.name || '??').replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase() || '??';
}

// One shared fetch for the chrome: projects, recent notifications / unread, and —
// only on Home and Build — running runs (list + per-project and total counts) and
// runs waiting on a human; the agent count loads only in Build.
// Everything the sidebar, the topbar "N running" pill AND the Pulse drawer need —
// all from the SAME query, mounted once via ShellDataProvider so the pill and the
// drawer are a single source (COMPONENT_MAP key behavior #2: "Pulse is global").
// Also owns the Pulse drawer open/close state so the topbar pill (toggle) and the
// drawer (panel) stay in sync. Polls live data on the 30s ADR-007 cadence.
const ShellDataContext = createContext({
    projects: [], runningRuns: [], runningByProject: {}, runningTotal: 0,
    waitingRuns: [], recentNotifs: [], agentCount: null, unread: 0,
    pulseOpen: false, togglePulse: () => {}, dismissWaiting: () => {},
    markNotifRead: () => {},
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

    // Mark one notification read locally (bell + Pulse share this list).
    const markNotifRead = (id) => {
        setRecentNotifs((list) => {
            const next = list.map((x) => (x.id === id ? { ...x, read: true } : x));
            setUnread(next.filter((x) => !x.read).length);
            return next;
        });
    };

    // Only fetch what the page on screen shows: runs feed Home (Live now /
    // Needs you) and Build; the agent count feeds the Build sidebar. Project
    // pages need neither, so they only pay for projects + notifications.
    const path = useLocation().pathname;
    const inBuild = path.startsWith('/forge');
    const wantsRuns = inBuild || path === '/studio';

    useEffect(() => {
        let cancelled = false;
        const loadNotifs = async () => {
            const notifs = await api.getNotifications(false).catch(() => []);
            if (cancelled) return;
            const nlist = Array.isArray(notifs) ? notifs : [];
            setRecentNotifs(nlist);
            setUnread(nlist.filter((x) => !x.read).length);
        };
        api.getProjects().catch(() => []).then((pj) => { if (!cancelled) setProjects(Array.isArray(pj) ? pj : []); });
        loadNotifs();
        const id = setInterval(loadNotifs, 30_000);
        return () => { cancelled = true; clearInterval(id); };
    }, []);

    useEffect(() => {
        if (!wantsRuns) return undefined;
        let cancelled = false;
        const loadRuns = async () => {
            const [runs, waiting] = await Promise.all([
                api.forge.listRuns({ status: 'running' }).catch(() => []),
                api.forge.listRuns({ outcome: 'needs_input', unresolved: true }).catch(() => []),
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
        };
        loadRuns();
        const id = setInterval(loadRuns, 30_000);
        return () => { cancelled = true; clearInterval(id); };
    }, [wantsRuns]);

    useEffect(() => {
        if (!inBuild) return;
        api.forge.listAgents().catch(() => []).then((agents) => setAgentCount(Array.isArray(agents) ? agents.length : null));
    }, [inBuild]);

    const value = {
        projects, runningRuns, runningByProject, runningTotal,
        waitingRuns, recentNotifs, agentCount, unread,
        pulseOpen, togglePulse, dismissWaiting, markNotifRead,
    };
    return <ShellDataContext.Provider value={value}>{children}</ShellDataContext.Provider>;
}

export function useShellData() {
    return useContext(ShellDataContext);
}
