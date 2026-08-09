import React, { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { Markdown } from '../components/Markdown';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { MentionInput } from '../components/MentionInput';
import { AttachmentsSection } from '../components/TaskDetail/AttachmentsSection';
import { RelationsSection } from '../components/TaskDetail/RelationsSection';
import { ROUTES } from '../routes';
import { setCurrentProjectId } from '../currentProject';
import {
    Clock,
    MessageSquare,
    Calendar,
    GitBranch,
    GitCommit,
    GitPullRequest,
    ExternalLink,
    Copy,
    Check,
    Pencil,
    CheckSquare,
    Square,
    Plus,
    X,
    Bot,
    Zap,
    DollarSign,
    AlertTriangle,
    ClipboardList,
    Activity as ActivityIcon,
    Play,
} from 'lucide-react';

const TABS = [
    { id: 'plan', label: 'Plan', icon: ClipboardList },
    { id: 'run', label: 'Run', icon: Play },
    { id: 'activity', label: 'Activity', icon: ActivityIcon },
];

const STATUS_OPTIONS = [
    { value: 'backlog', label: 'Backlog' },
    { value: 'todo', label: 'To Do' },
    { value: 'in_progress', label: 'In Progress' },
    { value: 'review', label: 'In Review' },
    { value: 'done', label: 'Done' },
];
const PRIORITY_OPTIONS = ['critical', 'high', 'medium', 'low'];

// Minimal run-status palette — mirrors RunDetail's STATUS_CONFIG for the
// states a task's single run actually reaches. Local so TaskPage doesn't
// depend on RunDetail's internals.
const RUN_STATUS = {
    ready:        { bg: '#3b82f6', label: 'Ready' },
    pending:      { bg: '#5f6368', label: 'Queued' },
    running:      { bg: '#f1c40f', label: 'Running' },
    interrupting: { bg: '#9aa0a6', label: 'Stopping…' },
    paused:       { bg: '#9aa0a6', label: 'Paused' },
    completed:    { bg: '#2ecc71', label: 'Completed' },
    failed:       { bg: '#e74c3c', label: 'Failed' },
    cancelled:    { bg: '#9aa0a6', label: 'Cancelled' },
};

const ACTIVE_RUN_STATUSES = new Set(['pending', 'running', 'interrupting']);

// 1 task = 1 run: the "current" run is simply the newest one.
export function pickCurrentRun(runs) {
    if (!Array.isArray(runs) || runs.length === 0) return null;
    return [...runs].sort(
        (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)
    )[0];
}

// When did Run.summary last change? While running it rolls every turn, so we
// stamp "now" on each change. First sighting of an already-finished run uses
// the run's own finish/create time instead of the moment we loaded the page.
export function summaryStamp(prevSummary, run, prevStamp, now) {
    if (!run || !run.summary) return null;
    if (run.summary === prevSummary) return prevStamp;
    if (prevSummary === null && run.status !== 'running') {
        return run.finished_at || run.created_at || now;
    }
    return now;
}

function formatBranchDisplay(val) {
    if (!val) return '';
    const treeMatch = val.match(/\/tree\/(.+)$/);
    if (treeMatch) return treeMatch[1];
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

function formatPrDisplay(val) {
    if (!val) return '';
    const prMatch = val.match(/github\.com\/[^/]+\/([^/]+)\/pull\/(\d+)/);
    if (prMatch) return `${prMatch[1]}#${prMatch[2]}`;
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

function formatDuration(ms) {
    if (ms == null) return '—';
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    return `${m}m ${s % 60}s`;
}

function relTime(value) {
    if (!value) return '';
    const d = new Date(value);
    const diff = Math.round((Date.now() - d.getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return d.toLocaleString();
}

export function TaskPage() {
    const { taskId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const [searchParams, setSearchParams] = useSearchParams();
    const tabParam = searchParams.get('tab');
    const tab = TABS.some(t => t.id === tabParam) ? tabParam : 'plan';
    const setTab = (t) => setSearchParams(prev => {
        const next = new URLSearchParams(prev);
        next.set('tab', t);
        return next;
    });

    const [task, setTask] = useState(null);
    const [activities, setActivities] = useState([]);
    const [comment, setComment] = useState('');
    const [loading, setLoading] = useState(true);
    const [commits, setCommits] = useState([]);
    const [projectRepos, setProjectRepos] = useState([]);
    const [dodItems, setDodItems] = useState([]);
    const [newDodText, setNewDodText] = useState('');
    const [editingBranch, setEditingBranch] = useState(false);
    const [branchValue, setBranchValue] = useState('');
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [prUrlValue, setPrUrlValue] = useState('');
    const [copiedField, setCopiedField] = useState(null);
    const [profiles, setProfiles] = useState([]);
    const [forgeAgents, setForgeAgents] = useState([]);
    const [pickingAgent, setPickingAgent] = useState(false);
    const [scheduling, setScheduling] = useState(false);

    // Edit mode for the core task fields (title + description). Status,
    // priority and assignee stay inline-editable in the Plan tab.
    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({
        title: '', description: '', status: 'backlog', priority: 'medium', assignee: '', tags: [],
        due_date: '',
    });

    // Single source of truth for live run state (DoD: "Live run state
    // propagates from Pulse query (single source)"). One poll feeds both the
    // header status pill and the Agent tab — nothing else fetches runs.
    const [run, setRun] = useState(null);
    const [summaryUpdatedAt, setSummaryUpdatedAt] = useState(null);
    const prevSummary = useRef(null);

    // The URL param can be a task key (AP-12) — Forge endpoints only accept
    // the primary id, so every forge call goes through the loaded task.
    const taskUid = task?.id;

    // The topbar's "New task" action is a global event; the listener normally
    // lives in ProjectLayout, which this route is not nested under.
    const [showCreate, setShowCreate] = useState(false);
    useEffect(() => {
        const open = () => setShowCreate(true);
        window.addEventListener('open-create-task', open);
        return () => window.removeEventListener('open-create-task', open);
    }, []);

    const loadTask = async () => {
        try {
            const data = await api.getTask(taskId);
            setTask(data);
            setDodItems(data.dod_items || []);
            setBranchValue(data.branch || '');
            setPrUrlValue(data.pr_url || '');
        } catch (err) { console.error(err); }
    };

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.getTask(taskId);
                setTask(data);
                setDodItems(data.dod_items || []);
                setBranchValue(data.branch || '');
                setPrUrlValue(data.pr_url || '');
                if (data.project_id) setCurrentProjectId(data.project_id);
                api.getProjectMembers(data.project_id).then(setProfiles).catch(() => {});
                const actData = await api.getActivity(taskId);
                setActivities(actData);
                const commitData = await api.listTaskCommits(taskId);
                if (Array.isArray(commitData)) setCommits(commitData);
                try {
                    const repoData = await api.listProjectRepos(data.project_id);
                    setProjectRepos(Array.isArray(repoData) ? repoData : []);
                } catch { setProjectRepos([]); }
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [taskId]);

    // Pulse: poll the task's single run. 5s while active, 30s once terminal.
    // Keyed on the task's real id, not the URL param — the side panel's
    // "Open full" link navigates by task key, and Forge resolves runs by id.
    useEffect(() => {
        if (!taskUid) return;
        let cancelled = false;
        let timer;
        const tick = async () => {
            try {
                const runs = await api.forge.listTaskRuns(taskUid);
                if (cancelled) return;
                const current = pickCurrentRun(runs);
                setSummaryUpdatedAt(prev =>
                    summaryStamp(prevSummary.current, current, prev, new Date().toISOString()));
                prevSummary.current = current?.summary || null;
                setRun(current);
                const cadence = current && ACTIVE_RUN_STATUSES.has(current.status) ? 5000 : 30000;
                timer = setTimeout(tick, cadence);
            } catch {
                if (!cancelled) timer = setTimeout(tick, 30000);
            }
        };
        tick();
        return () => { cancelled = true; clearTimeout(timer); };
    }, [taskUid]);

    // Keep the Activity tab live — agents and the daemon append activity while
    // the page is open, so poll it (matching the side panel's cadence) instead
    // of only loading once on mount.
    useEffect(() => {
        let cancelled = false;
        const poll = async () => {
            try {
                const data = await api.getActivity(taskId);
                if (!cancelled) setActivities(data);
            } catch { /* transient */ }
        };
        const interval = setInterval(poll, 3000);
        return () => { cancelled = true; clearInterval(interval); };
    }, [taskId]);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };

    const saveBranch = async (val) => {
        setEditingBranch(false);
        if (task && val !== (task.branch || '')) {
            await api.updateTask(taskId, { branch: val });
            loadTask();
        }
    };

    const savePrUrl = async (val) => {
        setEditingPrUrl(false);
        if (task && val !== (task.pr_url || '')) {
            await api.updateTask(taskId, { pr_url: val });
            loadTask();
        }
    };

    const startEditing = () => {
        setFormData({
            title: task.title || '',
            description: task.description || '',
            status: task.status || 'backlog',
            priority: task.priority || 'medium',
            assignee: task.assignee || '',
            tags: task.tags || [],
            // Date inputs want YYYY-MM-DD; API returns full ISO timestamps.
            due_date: task.due_date ? String(task.due_date).slice(0, 10) : '',
        });
        setIsEditing(true);
    };

    const cancelEditing = () => setIsEditing(false);

    const handleSave = async () => {
        try {
            await api.updateTask(taskId, {
                title: formData.title,
                description: formData.description,
                priority: formData.priority,
                assignee: formData.assignee,
                tags: formData.tags,
                // Empty string clears the due date (backend treats "" as null).
                due_date: formData.due_date || '',
            });
            // Status transitions go through the dedicated /move endpoint.
            if (formData.status && formData.status !== task.status) {
                await api.moveTask(taskId, formData.status);
            }
            setIsEditing(false);
            loadTask();
        } catch (err) {
            alert(err.message);
        }
    };

    const openAgentPicker = async () => {
        setPickingAgent(true);
        try {
            const data = await api.forge.listAgents();
            setForgeAgents((Array.isArray(data) ? data : []).filter(a => a.runtime_id));
        } catch (err) {
            console.error('Failed to load agents:', err);
            setForgeAgents([]);
        }
    };

    const handleScheduleRun = async (agentId) => {
        setScheduling(true);
        try {
            const result = await api.forge.prepareTaskRun(taskUid, agentId);
            setPickingAgent(false);
            const runId = result.id || result.run_id;
            if (runId) navigate(ROUTES.FORGE_RUN(runId));
        } catch (err) {
            console.error('Prepare run failed:', err);
            alert('Failed to prepare run: ' + (err.message || err));
        } finally {
            setScheduling(false);
        }
    };

    const toggleDodItem = async (index) => {
        const updated = dodItems.map((item, i) => i === index ? { ...item, checked: !item.checked } : item);
        setDodItems(updated);
        await api.updateTask(taskId, { dod_items: updated });
    };

    const addDodItem = async () => {
        if (!newDodText.trim()) return;
        const updated = [...dodItems, { text: newDodText.trim(), checked: false }];
        setDodItems(updated);
        setNewDodText('');
        await api.updateTask(taskId, { dod_items: updated });
    };

    const removeDodItem = async (index) => {
        const updated = dodItems.filter((_, i) => i !== index);
        setDodItems(updated);
        await api.updateTask(taskId, { dod_items: updated });
    };

    const handleComment = async (e) => {
        if (e) e.preventDefault();
        if (!comment.trim()) return;
        try {
            await api.addComment(taskId, { comment });
            setComment('');
            const actData = await api.getActivity(taskId);
            setActivities(actData);
        } catch (err) {
            alert(err.message);
        }
    };

    if (loading) return <div className="p-8 text-text-secondary">Loading task...</div>;
    if (!task) return <div className="p-8 text-red-400">Task not found.</div>;

    const priorityColors = {
        critical: '#ef4444',
        high: '#f97316',
        medium: '#eab308',
        low: '#6b7280',
    };
    const runStatus = run ? (RUN_STATUS[run.status] || { bg: '#5f6368', label: run.status }) : null;
    const runActive = run && ACTIVE_RUN_STATUSES.has(run.status);

    return (
        <div className="flex-1 bg-bg-app overflow-y-auto">
            <div className="max-w-[1700px] mx-auto px-6 py-5">
                {/* Header */}
                <div className="flex items-start justify-between gap-4 mb-4">
                    {isEditing ? (
                        <input
                            aria-label="Title"
                            className="flex-1 text-xl font-bold text-text-primary bg-bg-card border border-border-subtle rounded-lg px-3 py-1.5 focus:outline-none focus:border-accent-primary"
                            value={formData.title}
                            onChange={e => setFormData({ ...formData, title: e.target.value })}
                            autoFocus
                        />
                    ) : (
                        <h1 className="text-xl font-bold text-text-primary">{task.title}</h1>
                    )}
                    <div className="flex items-center gap-2 flex-shrink-0">
                        {isEditing ? (
                            <>
                                <button
                                    onClick={handleSave}
                                    title="Save changes"
                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-accent-primary hover:opacity-90 transition-opacity"
                                >
                                    <Check className="w-3.5 h-3.5" /> Save
                                </button>
                                <button
                                    onClick={cancelEditing}
                                    title="Cancel"
                                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary border border-border-subtle hover:text-text-primary transition-colors"
                                >
                                    <X className="w-3.5 h-3.5" /> Cancel
                                </button>
                            </>
                        ) : (
                            <button
                                onClick={startEditing}
                                title="Edit task"
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary border border-border-subtle hover:text-text-primary transition-colors"
                            >
                                <Pencil className="w-3.5 h-3.5" /> Edit
                            </button>
                        )}
                    </div>
                </div>

                {/* Tab bar */}
                <div className="flex gap-1 border-b border-border-subtle mb-5">
                    {TABS.map(t => {
                        const Icon = t.icon;
                        const active = t.id === tab;
                        return (
                            <button
                                key={t.id}
                                onClick={() => setTab(t.id)}
                                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                                    active
                                        ? 'border-accent-primary text-text-primary'
                                        : 'border-transparent text-text-tertiary hover:text-text-secondary'
                                }`}
                            >
                                <Icon className="w-4 h-4" /> {t.label}
                            </button>
                        );
                    })}
                </div>

                {tab === 'plan' && (
                    <PlanTab
                        task={task}
                        isEditing={isEditing}
                        formData={formData}
                        setFormData={setFormData}
                        profiles={profiles}
                        priorityColors={priorityColors}
                        dodItems={dodItems}
                        newDodText={newDodText}
                        setNewDodText={setNewDodText}
                        toggleDodItem={toggleDodItem}
                        addDodItem={addDodItem}
                        removeDodItem={removeDodItem}
                        projectRepos={projectRepos}
                        branchValue={branchValue}
                        setBranchValue={setBranchValue}
                        editingBranch={editingBranch}
                        setEditingBranch={setEditingBranch}
                        saveBranch={saveBranch}
                        prUrlValue={prUrlValue}
                        setPrUrlValue={setPrUrlValue}
                        editingPrUrl={editingPrUrl}
                        setEditingPrUrl={setEditingPrUrl}
                        savePrUrl={savePrUrl}
                        commits={commits}
                        copiedField={copiedField}
                        copyToClipboard={copyToClipboard}
                        taskId={taskId}
                        user={user}
                        comment={comment}
                        setComment={setComment}
                        handleComment={handleComment}
                        activities={activities}
                        loadTask={loadTask}
                    />
                )}

                {tab === 'run' && (
                    <AgentSection
                        run={run}
                        runStatus={runStatus}
                        runActive={runActive}
                        summaryUpdatedAt={summaryUpdatedAt}
                        task={task}
                        forgeAgents={forgeAgents}
                        pickingAgent={pickingAgent}
                        setPickingAgent={setPickingAgent}
                        scheduling={scheduling}
                        openAgentPicker={openAgentPicker}
                        handleScheduleRun={handleScheduleRun}
                    />
                )}

                {tab === 'activity' && <ActivityTab activities={activities} />}
            </div>

            {showCreate && (
                <CreateTaskModal
                    projectId={task.project_id}
                    onClose={() => setShowCreate(false)}
                    onCreated={() => setShowCreate(false)}
                />
            )}
        </div>
    );
}

function AgentSection({ run, runStatus, runActive, summaryUpdatedAt, task, forgeAgents, pickingAgent, setPickingAgent, scheduling, openAgentPicker, handleScheduleRun }) {
    const launcher = (
        <RunLauncher
            task={task}
            forgeAgents={forgeAgents}
            pickingAgent={pickingAgent}
            setPickingAgent={setPickingAgent}
            scheduling={scheduling}
            openAgentPicker={openAgentPicker}
            handleScheduleRun={handleScheduleRun}
            label={run ? 'Run again with agent' : 'Run with agent'}
        />
    );

    if (!run) {
        return (
            <div className="bg-bg-card border border-border-subtle rounded-xl p-5 shadow-sm flex items-center gap-4">
                <Bot className="w-8 h-8 text-text-tertiary flex-shrink-0" />
                <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-secondary">No agent run yet for this task.</p>
                    <p className="text-xs text-text-tertiary mt-0.5">Kick one off, or wait for an agent to pick it up.</p>
                </div>
                <div className="flex-shrink-0">{launcher}</div>
            </div>
        );
    }
    const totalTokens = (run.input_tokens || 0) + (run.output_tokens || 0);
    return (
        <div className="max-w-3xl space-y-6">
            {!runActive && launcher}
            {/* Run header */}
            <div className="flex items-center gap-3">
                <Link to={ROUTES.FORGE_RUN(run.id)} className="text-lg font-bold text-text-primary hover:text-accent-primary">
                    Run {run.id}
                </Link>
                {runStatus && (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold text-white" style={{ backgroundColor: runStatus.bg }}>
                        {runActive && (
                            <span className="relative flex h-2 w-2">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
                                <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
                            </span>
                        )}
                        {runStatus.label}
                    </span>
                )}
                {run.agent_name && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bg-hover text-xs text-text-secondary">
                        <Bot className="w-3 h-3" /> {run.agent_name}
                    </span>
                )}
                <Link to={ROUTES.FORGE_RUN(run.id)} className="ml-auto text-xs text-accent-primary hover:underline flex items-center gap-1">
                    Full run <ExternalLink className="w-3 h-3" />
                </Link>
            </div>

            {/* Rolling summary — updates each turn while running. */}
            <div className="bg-bg-card border border-border-subtle border-l-4 rounded-lg p-5 shadow-sm" style={{ borderLeftColor: runStatus?.bg }}>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary">Summary</h3>
                    {summaryUpdatedAt && (
                        <span className="text-[11px] text-text-tertiary flex items-center gap-1" title={new Date(summaryUpdatedAt).toLocaleString()}>
                            <Clock className="w-3 h-3" /> updated {relTime(summaryUpdatedAt)}
                        </span>
                    )}
                </div>
                {run.summary
                    ? <p className="text-sm text-text-primary whitespace-pre-wrap">{run.summary}</p>
                    : <p className="text-sm text-text-tertiary italic">{runActive ? 'Working…' : 'No summary yet.'}</p>}
            </div>

            {run.error && (
                <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-4">
                    <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" />
                        <pre className="text-xs text-text-secondary whitespace-pre-wrap font-mono">{run.error}</pre>
                    </div>
                </div>
            )}

            {/* Artifacts */}
            {Array.isArray(run.artifacts) && run.artifacts.length > 0 && (
                <div className="bg-bg-card border border-border-subtle rounded-lg p-5 shadow-sm">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary mb-3">Artifacts</h3>
                    <div className="space-y-1.5">
                        {run.artifacts.map((a, i) => (
                            <a key={i} href={a.url} target="_blank" rel="noopener noreferrer"
                               className="flex items-center gap-2 text-sm text-accent-primary hover:underline">
                                <ExternalLink className="w-3.5 h-3.5 flex-shrink-0" />
                                {a.label || a.url}
                            </a>
                        ))}
                    </div>
                </div>
            )}

            {/* Metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Metric icon={Clock} label="Duration" value={formatDuration(run.duration_ms)} />
                <Metric icon={Zap} label="Tokens" value={totalTokens > 0 ? totalTokens.toLocaleString() : '—'} />
                <Metric icon={DollarSign} label="Cost" value={run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : '—'} />
                <Metric icon={Bot} label="Model" value={run.model_used || '—'} />
            </div>
        </div>
    );
}

function RunLauncher({ task, forgeAgents, pickingAgent, setPickingAgent, scheduling, openAgentPicker, handleScheduleRun, label }) {
    return (
        <div>
            <div className="flex justify-end">
                <button
                    onClick={pickingAgent ? () => setPickingAgent(false) : openAgentPicker}
                    className="text-xs px-3 py-1.5 rounded-lg bg-accent-subtle text-accent-primary hover:bg-accent-subtle/80 inline-flex items-center gap-1.5 transition-colors"
                >
                    <Play className="w-3 h-3" /> {pickingAgent ? 'Cancel' : label}
                </button>
            </div>
            {pickingAgent && (
                <div className="mt-3 p-3 rounded-lg border border-border-subtle bg-bg-app/50 text-left">
                    {forgeAgents.length === 0 ? (
                        <p className="text-xs text-text-tertiary">No online agents bound to a runtime. Create one in Forge first.</p>
                    ) : (
                        <div className="space-y-1">
                            {[...forgeAgents].sort((a, b) => {
                                const aAssigned = task?.assignee && a.name === task.assignee;
                                const bAssigned = task?.assignee && b.name === task.assignee;
                                if (aAssigned && !bAssigned) return -1;
                                if (bAssigned && !aAssigned) return 1;
                                return (a.name || '').localeCompare(b.name || '');
                            }).map(a => {
                                const online = a.status === 'online';
                                const isAssigned = task?.assignee && a.name === task.assignee;
                                return (
                                    <button
                                        key={a.id}
                                        disabled={scheduling || !online}
                                        onClick={() => handleScheduleRun(a.id)}
                                        className={`w-full text-left px-3 py-2 rounded-md flex items-center gap-3 transition-colors border ${isAssigned ? 'border-accent-primary/40 bg-accent-subtle/30' : 'border-transparent'} ${online ? 'hover:bg-bg-hover cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}
                                    >
                                        <div className="w-7 h-7 rounded-md bg-bg-panel border border-border-subtle flex items-center justify-center text-xs font-bold text-text-secondary">
                                            {a.name?.[0]?.toUpperCase() || 'A'}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="text-sm text-text-primary truncate flex items-center gap-2">
                                                {a.name}
                                                {isAssigned && (
                                                    <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent-primary/15 text-accent-primary">assignee</span>
                                                )}
                                            </div>
                                            <div className="text-xs text-text-tertiary truncate">{a.model || a.runtime_type || 'no model'}</div>
                                        </div>
                                        <span className={`text-xs ${online ? 'text-green-400' : 'text-text-tertiary'}`}>
                                            {online ? 'online' : 'offline'}
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function Metric({ icon: Icon, label, value }) {
    return (
        <div className="bg-bg-card border border-border-subtle rounded-lg p-4 shadow-sm">
            <div className="flex items-center gap-1.5 text-text-tertiary mb-1">
                <Icon className="w-3.5 h-3.5" />
                <span className="text-[10px] font-bold uppercase">{label}</span>
            </div>
            <div className="text-sm font-semibold text-text-primary truncate" title={value}>{value}</div>
        </div>
    );
}

function ActivityTab({ activities }) {
    // Full, read-only timeline of everything that happened on the task
    // (status changes, comments, runs…). Posting comments lives on the Plan tab.
    return (
        <div className="max-w-3xl">
            <h2 className="text-sm font-bold uppercase text-text-tertiary mb-6 flex items-center gap-2">
                <ActivityIcon className="w-4 h-4" /> Activity
            </h2>
            {activities.length === 0 ? (
                <p className="text-sm text-text-tertiary italic">No activity yet.</p>
            ) : (
                <div className="space-y-6">
                    {activities.map(act => (
                        <div key={act.id} className="flex gap-4">
                            <div className="w-10 h-10 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary shadow-sm flex-shrink-0">
                                {act.actor?.[0]?.toUpperCase() || '?'}
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-3 mb-1">
                                    <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                                    <span className="text-xs text-text-tertiary">
                                        {new Date(act.created_at).toLocaleDateString()} at {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                    </span>
                                </div>
                                <div className="text-sm text-text-secondary break-words">
                                    <span className="text-accent-primary font-medium mr-1">{act.action}</span>
                                    {act.detail}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function CommentsSection({ user, comment, setComment, handleComment, activities, projectId }) {
    // Comments only — the full activity timeline lives in the board side panel.
    const comments = activities.filter(a => a.action === 'commented');
    return (
        <div>
            <h2 className="text-sm font-bold uppercase text-text-tertiary mb-4 flex items-center gap-2">
                <MessageSquare className="w-4 h-4" /> Comments
            </h2>

            <div className="flex gap-4 mb-8">
                <div className="w-10 h-10 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-sm text-accent-primary flex-shrink-0">
                    {user?.display_name?.[0]?.toUpperCase() || 'U'}
                </div>
                <form onSubmit={handleComment} className="flex-1">
                    <MentionInput
                        multiline
                        rows={3}
                        className="w-full bg-bg-card border border-border-subtle text-sm p-4 rounded-lg focus:outline-none focus:border-accent-primary transition-colors h-24 resize-none shadow-sm"
                        placeholder="Add a comment… (@ to mention an agent)"
                        value={comment}
                        onChange={setComment}
                        onSubmit={handleComment}
                        projectId={projectId}
                    />
                    <div className="mt-2 flex justify-end">
                        <button className="btn btn-primary">Add Comment</button>
                    </div>
                </form>
            </div>

            <div className="space-y-6">
                {comments.length === 0 && <p className="text-sm text-text-tertiary italic">No comments yet.</p>}
                {comments.map(act => (
                    <div key={act.id} className="flex gap-4 group">
                        <div className="w-10 h-10 rounded-full bg-bg-card border border-border-subtle flex items-center justify-center font-bold text-xs text-text-tertiary shadow-sm flex-shrink-0">
                            {act.actor?.[0]?.toUpperCase() || '?'}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-3 mb-1">
                                <span className="text-sm font-bold text-text-primary">{act.actor}</span>
                                <span className="text-xs text-text-tertiary">
                                    {new Date(act.created_at).toLocaleDateString()} at {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                            </div>
                            <div className="text-sm text-text-secondary bg-bg-card border border-border-subtle rounded-lg px-4 py-3 break-words">
                                {act.detail}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

function PlanTab(props) {
    const {
        task, isEditing, formData, setFormData, profiles, priorityColors, dodItems, newDodText, setNewDodText,
        toggleDodItem, addDodItem, removeDodItem, projectRepos,
        branchValue, setBranchValue, editingBranch, setEditingBranch, saveBranch,
        prUrlValue, setPrUrlValue, editingPrUrl, setEditingPrUrl, savePrUrl,
        commits, copiedField, copyToClipboard,
        taskId, user, comment, setComment, handleComment, activities,
        loadTask,
    } = props;

    return (
        <div className="space-y-8">
            <section aria-labelledby="task-overview-heading" data-testid="task-overview-section">
                <h2 id="task-overview-heading" className="text-[11px] font-bold uppercase tracking-wider text-text-tertiary mb-3">
                    Overview &amp; planning
                </h2>

                {/* Same 4-across card band as the delivery row below, so the
                    brief, the details and the dependencies read as one grid
                    instead of a wide column beside a narrow sidebar. */}
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 items-start">
                <div className="sm:col-span-2 min-w-0 bg-bg-card border border-border-subtle rounded-xl p-5 shadow-sm">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary mb-3">Description</h3>
                    {isEditing ? (
                        <textarea
                            aria-label="Description"
                            className="w-full min-h-[10rem] text-sm text-text-primary leading-relaxed bg-bg-app p-3 rounded-lg border border-border-subtle focus:outline-none focus:border-accent-primary resize-y"
                            value={formData.description}
                            onChange={e => setFormData({ ...formData, description: e.target.value })}
                            placeholder="Describe this task… (Markdown supported)"
                        />
                    ) : (
                        <div className="text-sm text-text-secondary leading-relaxed break-words overflow-x-auto">
                            {task.description
                                ? <Markdown>{task.description}</Markdown>
                                : <span className="italic text-text-tertiary">No description provided.</span>}
                        </div>
                    )}
                </div>

                <div className="min-w-0 bg-bg-card border border-border-subtle rounded-xl p-5 shadow-sm">
                    <h3 className="text-xs font-bold uppercase text-text-tertiary mb-3">Details</h3>

                    <div className="grid grid-cols-2 gap-x-4 gap-y-4">
                        <div>
                            <label htmlFor="task-status" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Status</label>
                            {isEditing ? (
                                <select
                                    id="task-status"
                                    aria-label="Status"
                                    className="bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded-lg w-full"
                                    value={formData.status}
                                    onChange={e => setFormData({ ...formData, status: e.target.value })}
                                >
                                    {STATUS_OPTIONS.map(s => (
                                        <option key={s.value} value={s.value}>{s.label}</option>
                                    ))}
                                </select>
                            ) : (
                                <span className={`text-xs px-2.5 py-1 rounded font-bold uppercase tracking-wider
                                    ${task.status === 'done' ? 'bg-green-500/20 text-green-400' : 'bg-accent-subtle text-accent-primary'}
                                `}>
                                    {task.status.replace('_', ' ')}
                                </span>
                            )}
                        </div>

                        <div>
                            <label htmlFor="task-priority" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Priority</label>
                            {isEditing ? (
                                <select
                                    id="task-priority"
                                    aria-label="Priority"
                                    className="bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded-lg w-full capitalize"
                                    value={formData.priority}
                                    onChange={e => setFormData({ ...formData, priority: e.target.value })}
                                >
                                    {PRIORITY_OPTIONS.map(p => (
                                        <option key={p} value={p}>{p}</option>
                                    ))}
                                </select>
                            ) : (
                                <div className="flex items-center gap-2">
                                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: priorityColors[task.priority] }} />
                                    <span className="text-sm text-text-secondary capitalize">{task.priority}</span>
                                </div>
                            )}
                        </div>

                        <div>
                            <label htmlFor="task-assignee" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Assignee</label>
                            {isEditing ? (
                                <select
                                    id="task-assignee"
                                    aria-label="Assignee"
                                    className="bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded-lg w-full"
                                    value={formData.assignee}
                                    onChange={e => setFormData({ ...formData, assignee: e.target.value })}
                                >
                                    <option value="">Unassigned</option>
                                    {profiles.map(p => (
                                        <option key={p.id} value={p.name}>{p.display_name}</option>
                                    ))}
                                </select>
                            ) : (
                                <div className="flex items-center gap-2">
                                    <div className="w-6 h-6 rounded-full bg-accent-subtle flex items-center justify-center text-[10px] font-bold text-accent-primary flex-shrink-0">
                                        {task.assignee ? task.assignee[0].toUpperCase() : '?'}
                                    </div>
                                    <span className="text-sm text-text-secondary">{task.assignee || 'Unassigned'}</span>
                                </div>
                            )}
                        </div>

                        <div>
                            <label htmlFor="task-tags" className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Labels</label>
                            {isEditing ? (
                                <input
                                    id="task-tags"
                                    aria-label="Tags"
                                    className="bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded-lg w-full"
                                    placeholder="comma, separated, tags"
                                    value={(formData.tags || []).join(', ')}
                                    onChange={e => setFormData({
                                        ...formData,
                                        tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean),
                                    })}
                                />
                            ) : (
                                <div className="flex flex-wrap gap-1.5">
                                    {(task.tags || []).length > 0 ? task.tags.map(t => (
                                        <span key={t} className="text-[10px] font-medium bg-bg-app px-2 py-0.5 rounded border border-border-subtle text-text-secondary">
                                            {t}
                                        </span>
                                    )) : <span className="text-xs text-text-tertiary italic">None</span>}
                                </div>
                            )}
                        </div>

                        <div>
                            <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Epic</label>
                            {task.epic_name ? (
                                task.epic_id ? (
                                    <Link
                                        to={ROUTES.STUDIO_EPIC(task.epic_id)}
                                        className="text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase tracking-wider hover:underline"
                                        style={{ backgroundColor: `${task.epic_color || '#7c4dff'}20`, color: task.epic_color || '#7c4dff' }}
                                        title={`Open epic: ${task.epic_name}`}
                                    >
                                        {task.epic_name}
                                    </Link>
                                ) : (
                                    <span
                                        className="text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase tracking-wider"
                                        style={{ backgroundColor: `${task.epic_color || '#7c4dff'}20`, color: task.epic_color || '#7c4dff' }}
                                    >
                                        {task.epic_name}
                                    </span>
                                )
                            ) : <span className="text-xs text-text-tertiary italic">None</span>}
                        </div>

                        {projectRepos.length > 0 && (
                            <div className="col-span-2">
                                <label className="text-[10px] font-bold uppercase text-text-tertiary block mb-2">Repos</label>
                                <div className="flex flex-wrap gap-1.5">
                                    {(task.repos || []).length > 0
                                        ? task.repos.map(n => (
                                            <span key={n} className="text-[10px] font-medium bg-bg-app px-2 py-0.5 rounded border border-border-subtle text-text-secondary">{n}</span>
                                        ))
                                        : <span className="text-xs text-text-tertiary italic">none — falls back to project's primary repo</span>}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Parent, subtasks, dependencies and milestone are planning
                    context, so keep them above the fold. */}
                <RelationsSection task={task} onChanged={loadTask} isEditing={isEditing} />
                </div>
            </section>

            <section
                aria-labelledby="task-collaboration-heading"
                data-testid="task-collaboration-section"
                className="border-t border-border-subtle pt-6"
            >
                <h2 id="task-collaboration-heading" className="text-[11px] font-bold uppercase tracking-wider text-text-tertiary mb-3">
                    Collaboration &amp; delivery
                </h2>

                {/* Keep the delivery cards aligned as a single band. Each card
                    owns its overflow so long lists do not create uneven
                    floating panels or push the discussion down the page. */}
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6 items-stretch">

                {/* Definition of Done */}
                <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm sm:h-80 overflow-y-auto">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-xs font-bold uppercase text-text-primary flex items-center gap-1.5">
                            <CheckSquare className="w-3.5 h-3.5" /> Definition of Done
                        </h3>
                        {dodItems.length > 0 && (
                            <span className="text-xs text-text-secondary">
                                {dodItems.filter(i => i.checked).length}/{dodItems.length}
                            </span>
                        )}
                    </div>

                    {dodItems.length > 0 && (
                        <div className="w-full bg-bg-app rounded-full h-1.5 mb-3">
                            <div
                                className="h-1.5 rounded-full transition-all duration-300"
                                style={{
                                    width: `${dodItems.length ? (dodItems.filter(i => i.checked).length / dodItems.length) * 100 : 0}%`,
                                    backgroundColor: dodItems.every(i => i.checked) ? '#2ecc71' : '#7c4dff',
                                }}
                            />
                        </div>
                    )}

                    <div className="space-y-1">
                        {dodItems.map((item, i) => (
                            <div key={i} className="flex items-center gap-2 group py-1 px-2 rounded hover:bg-bg-hover transition-colors">
                                <button onClick={() => toggleDodItem(i)} className="flex-shrink-0 text-text-secondary hover:text-accent-primary transition-colors">
                                    {item.checked ? <CheckSquare className="w-4 h-4 text-green-500" /> : <Square className="w-4 h-4" />}
                                </button>
                                <span className={`text-sm flex-1 ${item.checked ? 'line-through text-text-tertiary' : 'text-text-primary'}`}>{item.text}</span>
                                <button onClick={() => removeDodItem(i)} className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all p-0.5">
                                    <X className="w-3 h-3" />
                                </button>
                            </div>
                        ))}
                    </div>

                    <div className="flex items-center gap-2 mt-2">
                        <input
                            className="flex-1 bg-bg-app border border-border-subtle text-sm text-text-primary p-1.5 rounded focus:outline-none focus:border-accent-primary"
                            placeholder="Add DOD item..."
                            value={newDodText}
                            onChange={(e) => setNewDodText(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && addDodItem()}
                        />
                        <button onClick={addDodItem} className="p-1.5 rounded hover:bg-bg-hover text-text-tertiary hover:text-accent-primary transition-colors">
                            <Plus className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                {/* Git Integration */}
                <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm sm:h-80 overflow-y-auto">
                    <h3 className="text-xs font-bold uppercase text-text-primary flex items-center gap-1.5 mb-4">
                        <GitBranch className="w-3.5 h-3.5" /> Branch &amp; PR
                    </h3>

                    <div className="mb-4">
                        <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Branch</div>
                        {editingBranch ? (
                            <input
                                className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded font-mono text-text-primary focus:outline-none focus:border-accent-primary"
                                value={branchValue}
                                onChange={e => setBranchValue(e.target.value)}
                                onBlur={() => saveBranch(branchValue)}
                                onKeyDown={e => e.key === 'Enter' && saveBranch(branchValue)}
                                autoFocus
                            />
                        ) : (
                            <div className="flex items-center gap-1.5">
                                {branchValue ? (
                                    <>
                                        {branchValue.startsWith('http') ? (
                                            <a href={branchValue} target="_blank" rel="noopener noreferrer" className="text-sm font-mono text-accent-primary hover:underline truncate">
                                                {formatBranchDisplay(branchValue)}
                                            </a>
                                        ) : (
                                            <span className="text-sm font-mono text-text-primary truncate">{branchValue}</span>
                                        )}
                                        <button onClick={() => setEditingBranch(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                            <Pencil className="w-3 h-3" />
                                        </button>
                                        <button onClick={() => copyToClipboard(branchValue, 'branch')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                            {copiedField === 'branch' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                        </button>
                                    </>
                                ) : (
                                    <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingBranch(true)}>No branch set</span>
                                )}
                            </div>
                        )}
                    </div>

                    <div className="mb-4">
                        <div className="text-[10px] font-bold uppercase text-text-secondary mb-1">Pull Request</div>
                        {editingPrUrl ? (
                            <input
                                className="w-full px-2 py-1.5 text-sm bg-bg-app border border-border-subtle rounded text-text-primary focus:outline-none focus:border-accent-primary"
                                value={prUrlValue}
                                onChange={e => setPrUrlValue(e.target.value)}
                                onBlur={() => savePrUrl(prUrlValue)}
                                onKeyDown={e => e.key === 'Enter' && savePrUrl(prUrlValue)}
                                placeholder="https://github.com/..."
                                autoFocus
                            />
                        ) : (
                            <div className="flex items-center gap-1.5">
                                {prUrlValue ? (
                                    <>
                                        <a href={prUrlValue} target="_blank" rel="noopener noreferrer" className="text-sm text-accent-primary hover:underline truncate">
                                            {formatPrDisplay(prUrlValue)}
                                        </a>
                                        <button onClick={() => setEditingPrUrl(true)} className="p-0.5 text-text-tertiary hover:text-text-secondary transition-colors flex-shrink-0" title="Edit">
                                            <Pencil className="w-3 h-3" />
                                        </button>
                                        <button onClick={() => copyToClipboard(prUrlValue, 'pr')} className="p-0.5 text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0" title="Copy">
                                            {copiedField === 'pr' ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                                        </button>
                                    </>
                                ) : (
                                    <span className="text-xs text-text-tertiary italic cursor-pointer hover:text-text-secondary" onClick={() => setEditingPrUrl(true)}>No PR linked</span>
                                )}
                            </div>
                        )}
                    </div>

                    {commits.length > 0 && (
                        <>
                            <div className="text-[10px] font-bold uppercase text-text-secondary mb-1.5">Commits & PRs ({commits.length})</div>
                            <div className="space-y-1.5">
                                {commits.map((c) => (
                                    <div key={c.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-bg-app border border-border-subtle/30 text-sm">
                                        {c.kind === 'pr'
                                            ? <GitPullRequest className="w-3.5 h-3.5 text-purple-400 flex-shrink-0" />
                                            : <GitCommit className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
                                        }
                                        <div className="flex-1 min-w-0">
                                            <div className="text-text-primary truncate text-xs">
                                                {c.kind === 'pr' ? `#${c.pr_number} ` : `${c.sha.slice(0, 7)} `}{c.message}
                                            </div>
                                            <div className="text-[10px] text-text-secondary">
                                                {c.author}{c.branch ? ` on ${c.branch}` : ''}
                                                {c.kind === 'pr' && c.pr_state && (
                                                    <span className={`ml-1.5 px-1 py-0.5 rounded text-[9px] font-medium ${
                                                        c.pr_state === 'merged' ? 'bg-purple-500/20 text-purple-400' :
                                                        c.pr_state === 'open' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                                                    }`}>{c.pr_state}</span>
                                                )}
                                            </div>
                                        </div>
                                        {c.url && (
                                            <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-text-tertiary hover:text-accent-primary transition-colors flex-shrink-0">
                                                <ExternalLink className="w-3 h-3" />
                                            </a>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </div>

                {/* Files live in the side column now (no separate tab). The
                    AttachmentsSection brings its own header + top border, so it
                    sits directly in the card. */}
                <div className="bg-bg-card border border-border-subtle rounded-xl px-6 pb-6 shadow-sm sm:h-80 overflow-y-auto">
                    <AttachmentsSection taskId={taskId} />
                </div>

                <div className="bg-bg-card border border-border-subtle rounded-xl p-6 shadow-sm sm:h-80 overflow-y-auto">
                    <h3 className="text-xs font-bold uppercase text-text-secondary mb-4">Timestamps</h3>
                    <div className="space-y-3">
                        <div className="flex items-center gap-2 text-text-secondary">
                            <Calendar className="w-3.5 h-3.5 flex-shrink-0" />
                            <span className="text-xs flex-1">Due</span>
                            {isEditing ? (
                                <input
                                    type="date"
                                    aria-label="Due date"
                                    className="input input-date text-xs py-1 px-2 w-auto"
                                    value={formData.due_date || ''}
                                    onChange={e => setFormData({ ...formData, due_date: e.target.value })}
                                />
                            ) : (
                                <span className="text-xs" data-testid="task-due-date">
                                    {task.due_date
                                        ? new Date(task.due_date).toLocaleDateString()
                                        : 'Not set'}
                                </span>
                            )}
                        </div>
                        <div className="flex items-center gap-2 text-text-secondary">
                            <Calendar className="w-3.5 h-3.5" />
                            <span className="text-xs">Created: {new Date(task.created_at).toLocaleDateString()}</span>
                        </div>
                        <div className="flex items-center gap-2 text-text-secondary">
                            <Clock className="w-3.5 h-3.5" />
                            <span className="text-xs">Updated: {new Date(task.updated_at).toLocaleDateString()}</span>
                        </div>
                    </div>
                </div>
                </div>

                <div className="mt-8">
                    <CommentsSection
                        user={user}
                        comment={comment}
                        setComment={setComment}
                        handleComment={handleComment}
                        activities={activities}
                        projectId={task.project_id}
                    />
                </div>
            </section>
        </div>
    );
}
