import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useOutletContext } from 'react-router-dom';
import { api } from '../api';
import { C, DEPLOY_KEYFRAMES, IN_FLIGHT, statusOf } from '../components/deploy/theme';
import { NotConnected, NoDeployYet } from '../components/deploy/NotConnected';
import { ConnectWizard } from '../components/deploy/ConnectWizard';
import { PreviewBar } from '../components/deploy/PreviewBar';
import { LivePreview } from '../components/deploy/LivePreview';
import { BranchList } from '../components/deploy/BranchList';
import { LogsPanel } from '../components/deploy/LogsPanel';
import { ProviderSettings } from '../components/deploy/ProviderSettings';

// Deploy tab — a port of design/deploy/Deploy.dc.html.
//
// The payoff moment: connect a provider once, then main redeploys on every push
// and any branch previews on demand. The Live card owns the page; branches sit
// quietly below; the provider is quiet chrome. While anything is queued or
// building we poll, because a deployment must never silently change colour.

const POLL_MS = 6000;

export function Deploy() {
    const { projectId } = useParams();
    const outlet = useOutletContext();
    const projectName = outlet?.board?.project?.name || 'this project';

    const [connection, setConnection] = useState(null);
    const [entries, setEntries] = useState([]);
    const [selectedBranch, setSelectedBranch] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [showWizard, setShowWizard] = useState(false);
    const [logsFor, setLogsFor] = useState(null);
    const [busyBranch, setBusyBranch] = useState(null);
    const [barVisible, setBarVisible] = useState(true);
    const [pinned, setPinned] = useState(true);

    const branchListRef = useRef(null);

    const loadDeployments = useCallback(async () => {
        const res = await api.getDeployments(projectId);
        const list = res.branches || [];
        setEntries(list);
        return list;
    }, [projectId]);

    const load = useCallback(async () => {
        try {
            const conn = await api.getDeployProvider(projectId);
            const connected = conn && conn.connected !== false && conn.provider;
            setConnection(connected ? conn : null);
            if (connected) await loadDeployments();
            setError(null);
        } catch (err) {
            setError(err.message || 'Failed to load deployments');
        } finally {
            setLoading(false);
        }
    }, [projectId, loadDeployments]);

    useEffect(() => { load(); }, [load]);

    // Default to main (or the first branch) once, then leave the user's choice alone.
    useEffect(() => {
        if (selectedBranch || entries.length === 0) return;
        setSelectedBranch((entries.find(e => e.is_main) || entries[0]).branch);
    }, [entries, selectedBranch]);

    // Poll only while something is in flight. Stop as soon as everything settles.
    const anyInFlight = useMemo(() => entries.some(e => IN_FLIGHT.has(statusOf(e.deployment))), [entries]);
    const loadRef = useRef(loadDeployments);
    useEffect(() => { loadRef.current = loadDeployments; }, [loadDeployments]);
    useEffect(() => {
        if (!anyInFlight) return undefined;
        const t = setInterval(() => {
            if (document.visibilityState === 'visible') loadRef.current().catch(() => {});
        }, POLL_MS);
        return () => clearInterval(t);
    }, [anyInFlight]);

    // Compute current early (before any conditional returns) so useMemo is always called in same order (Rules of Hooks).
    const current = useMemo(() => entries.find(e => e.branch === selectedBranch) || entries[0], [entries, selectedBranch]);

    const runAction = useCallback(async (branch, fn, optimistic) => {
        setBusyBranch(branch);
        if (optimistic) {
            // Optimistic update for snappy UI (AP-433 perf): show queued/building immediately so action doesn't feel slow
            setEntries(prev => prev.map(e => {
                if (e.branch !== branch) return e;
                const base = e.deployment || { id: 'opt-' + Date.now() };
                return { ...e, deployment: { ...base, status: optimistic, status_reason: 'Queued — starting…', updated_at: new Date().toISOString() } };
            }));
        }
        try {
            await fn();
            await loadDeployments();
        } catch (err) {
            setError(err.message);
        } finally {
            setBusyBranch(null);
        }
    }, [loadDeployments]);

    const deployBranch = useCallback((entry) => runAction(entry.branch, () => api.createDeployment(projectId, entry.branch), 'queued'), [runAction, projectId]);
    const redeployEntry = useCallback((entry) => runAction(entry.branch, () => (
        entry.deployment
            ? api.redeployDeployment(projectId, entry.deployment.id)
            : api.createDeployment(projectId, entry.branch)
    ), 'queued'), [runAction, projectId]);
    const stopDeployment = useCallback((deploymentId) => {
        const entry = entries.find(e => e.deployment?.id === deploymentId);
        return runAction(entry?.branch, () => api.stopDeployment(projectId, deploymentId), 'stopped');
    }, [entries, runAction, projectId]);

    const openLogs = useCallback((deploymentId) => {
        const entry = entries.find(e => e.deployment?.id === deploymentId);
        if (entry) setLogsFor({ ...entry.deployment, branch: entry.branch });
    }, [entries]);

    if (loading) return <div className="p-8 text-center text-text-secondary">Loading deployments…</div>;

    const styleTag = <style>{DEPLOY_KEYFRAMES}</style>;

    if (!connection) {
        return (
            <div style={{ background: C.bg }}>
                {styleTag}
                {error && <ErrorBar message={error} onDismiss={() => setError(null)} />}
                <NotConnected projectName={projectName} onConnect={() => setShowWizard(true)} />
                {showWizard && (
                    <ConnectWizard
                        projectId={projectId}
                        onClose={() => setShowWizard(false)}
                        onConnected={async () => { setShowWizard(false); setLoading(true); await load(); }}
                    />
                )}
            </div>
        );
    }

    const mainEntry = entries.find(e => e.is_main);
    if (entries.length === 0 || (mainEntry && !mainEntry.deployment && entries.every(e => !e.deployment))) {
        return (
            <div style={{ background: C.bg }}>
                {styleTag}
                {error && <ErrorBar message={error} onDismiss={() => setError(null)} />}
                <NoDeployYet
                    providerName={connection.provider}
                    busy={!!busyBranch}
                    onDeployMain={() => runAction('main', () => api.createDeployment(projectId, mainEntry?.branch || 'main'), 'queued')}
                />
                <div style={{ padding: '0 40px 40px', display: 'flex', justifyContent: 'center' }}>
                    <ProviderSettings projectId={projectId} connection={connection} onChanged={load} />
                </div>
            </div>
        );
    }

    return (
        <>
            {styleTag}

            {barVisible && (
                <PreviewBar
                    entries={entries}
                    selectedBranch={current.branch}
                    onSelectBranch={setSelectedBranch}
                    onDeployNew={() => branchListRef.current?.scrollIntoView({ behavior: 'smooth' })}
                    onRedeploy={() => redeployEntry(current)}
                    pinned={pinned}
                    onTogglePin={() => setPinned(p => !p)}
                    busy={busyBranch === current.branch}
                />
            )}

            {error && <ErrorBar message={error} onDismiss={() => setError(null)} />}

            <div style={{ padding: '8px 16px 20px', minHeight: 0 }}>
                <button
                    onClick={() => setBarVisible(!barVisible)}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: C.textMuted, padding: '5px 10px', border: `1px solid ${C.border}`, borderRadius: 7, background: 'transparent', cursor: 'pointer', fontFamily: 'inherit', marginBottom: 8 }}
                >
                    {barVisible ? 'Hide preview bar' : 'Show preview bar'}
                </button>

                <LivePreview entry={current} onOpenLogs={openLogs} />

                <div ref={branchListRef} style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 520px', minWidth: 0 }}>
                        <BranchList
                            entries={entries}
                            onPreview={deployBranch}
                            onRedeploy={redeployEntry}
                            onStop={stopDeployment}
                            onOpenLogs={openLogs}
                            busyBranch={busyBranch}
                        />
                    </div>
                    <ProviderSettings projectId={projectId} connection={connection} onChanged={load} />
                </div>
            </div>

            {logsFor && <LogsPanel projectId={projectId} deployment={logsFor} onClose={() => setLogsFor(null)} />}
        </>
    );
}

function ErrorBar({ message, onDismiss }) {
    return (
        <div role="alert" style={{ margin: '12px 40px 0', padding: '9px 12px', borderRadius: 9, background: 'rgba(248,81,73,.07)', border: '1px solid rgba(248,81,73,.32)', color: C.badText, fontSize: 11.5, display: 'flex', gap: 10 }}>
            <span style={{ flex: 1 }}>{message}</span>
            <button onClick={onDismiss} style={{ background: 'none', border: 'none', color: C.badText, cursor: 'pointer', fontFamily: 'inherit' }}>Dismiss</button>
        </div>
    );
}
