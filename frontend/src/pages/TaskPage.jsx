import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { CreateTaskModal } from '../components/CreateTaskModal';
import { PlanTab } from '../components/TaskDetail/PlanTab';
import {
    AgentSection, RUN_STATUS, ACTIVE_RUN_STATUSES, pickCurrentRun, summaryStamp,
} from '../components/TaskDetail/RunTab';
import { ActivityTab } from '../components/TaskDetail/ActivityFeed';
import { TitleEditor } from '../components/TaskDetail/TextDraft';
import { keepSameActivity, keepSameJson } from '../lib/pollState';
import { useVisiblePoll } from '../lib/useVisiblePoll';
import { useShellData } from '../components/shell/shellData';
import { ROUTES } from '../routes';
import { Breadcrumbs } from '../components/Breadcrumbs';
import { setCurrentProjectId } from '../currentProject';
import {
    Check,
    Pencil,
    X,
    ClipboardList,
    Activity as ActivityIcon,
    Play,
} from 'lucide-react';

// Re-exported: these pure helpers moved with the Run tab but are still tested here.
export { pickCurrentRun, summaryStamp };

const PRIORITY_COLORS = { critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#6b7280' };

const TABS = [
    { id: 'plan', label: 'Plan', icon: ClipboardList },
    { id: 'run', label: 'Run', icon: Play },
    { id: 'activity', label: 'Activity', icon: ActivityIcon },
];

export function TaskPage() {
    const { taskId } = useParams();
    // Keyed by task: switching tasks remounts the page, so typed drafts, edit
    // mode and form state from the previous task can never reach the next one.
    return <TaskPageBody key={taskId} />;
}

function TaskPageBody() {
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
    const [loading, setLoading] = useState(true);
    const [commits, setCommits] = useState([]);
    const [projectRepos, setProjectRepos] = useState([]);
    const [dodItems, setDodItems] = useState([]);
    const [newDodText, setNewDodText] = useState('');
    const [profiles, setProfiles] = useState([]);
    const [scheduling, setScheduling] = useState(false);
    const [epics, setEpics] = useState([]);

    // Edit mode for the core task fields (title + description). Status,
    // priority and assignee stay inline-editable in the Plan tab.
    const [isEditing, setIsEditing] = useState(false);
    const [formData, setFormData] = useState({
        title: '', description: '', status: 'backlog', priority: 'medium', assignee: '', tags: [], due_date: '',
    });

    // Single source of truth for live run state (DoD: "Live run state
    // propagates from Pulse query (single source)"). One poll feeds both the
    // header status pill and the Agent tab — nothing else fetches runs.
    const [run, setRun] = useState(null);
    const [summaryUpdatedAt, setSummaryUpdatedAt] = useState(null);
    const prevSummary = useRef(null);

    // Title and description drafts live in their own inputs (TitleEditor /
    // DescriptionEditor); they report here by ref so typing never re-renders
    // the page. Save merges them over formData.
    // The refs also reseed the editors when their tab or section remounts, so
    // switching tabs never loses typed text or shows stale text that Save would
    // then overwrite.
    const draft = useRef({});
    const commentDraft = useRef('');
    const onTitleDraft = useCallback(v => { draft.current.title = v; }, []);
    const { projects } = useShellData();

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

    const loadTask = useCallback(async () => {
        try {
            const data = await api.getTask(taskId);
            setTask(data);
            setDodItems(data.dod_items || []);
        } catch (err) { console.error(err); }
    }, [taskId]);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await api.getTask(taskId);
                setTask(data);
                setDodItems(data.dod_items || []);
                if (data.project_id) setCurrentProjectId(data.project_id);
                api.getProjectMembers(data.project_id).then(setProfiles).catch(() => {});
                api.getEpics(data.project_id).then(d => setEpics(Array.isArray(d) ? d : [])).catch(() => {});
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

    // Pulse: the task's single run. Keyed on the task's real id, not the URL
    // param — the side panel's "Open full" link navigates by task key, and
    // Forge resolves runs by id.
    const loadRun = useCallback(async () => {
        if (!taskUid) return;
        try {
            const runs = await api.forge.listTaskRuns(taskUid);
            const current = pickCurrentRun(runs);
            setSummaryUpdatedAt(prev =>
                summaryStamp(prevSummary.current, current, prev, new Date().toISOString()));
            prevSummary.current = current?.summary || null;
            setRun(prev => keepSameJson(prev, current));
        } catch { /* transient */ }
    }, [taskUid]);
    useEffect(() => { loadRun(); }, [loadRun]);

    // Keep the run and the Activity tab live — agents and the daemon append
    // activity while the page is open. 5 s only while a run is active, 30 s
    // otherwise, and never while the browser tab is hidden.
    const runActive = !!run && ACTIVE_RUN_STATUSES.has(run.status);
    useVisiblePoll(async () => {
        loadRun();
        try {
            const data = await api.getActivity(taskId);
            setActivities(prev => keepSameActivity(prev, data));
        } catch { /* transient */ }
    }, runActive ? 5000 : 30000, taskId);

    // Dropdown fields save on change when the page is not in edit mode.
    const saveField = useCallback(async (patch) => {
        try {
            if (patch.status !== undefined) await api.moveTask(taskId, patch.status);
            else await api.updateTask(taskId, patch);
            loadTask();
        } catch (err) {
            alert(err.message);
        }
    }, [taskId, loadTask]);

    const startEditing = () => {
        draft.current = {};
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
                title: draft.current.title ?? formData.title,
                description: draft.current.description ?? formData.description,
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

    const handleRunWithAgent = async () => {
        setScheduling(true);
        try {
            const agents = await api.forge.listAgents();
            const agent = (Array.isArray(agents) ? agents : []).find(a => a.runtime_id && a.name === task.assignee);
            if (!agent) throw new Error('The assigned agent has no runtime. Set one up first.');
            const result = await api.forge.prepareTaskRun(taskUid, agent.id);
            const runId = result.id || result.run_id;
            if (runId) navigate(ROUTES.FORGE_RUN(runId));
        } catch (err) {
            console.error('Prepare run failed:', err);
            alert('Failed to prepare run: ' + (err.message || err));
        } finally {
            setScheduling(false);
        }
    };

    // Stable handlers (read the latest list through refs) so the memoized
    // PlanTab is not re-rendered by unrelated page state.
    const dodRef = useRef(dodItems);
    dodRef.current = dodItems;
    const newDodRef = useRef(newDodText);
    newDodRef.current = newDodText;
    const saveDod = useCallback(async (updated) => {
        setDodItems(updated);
        await api.updateTask(taskId, { dod_items: updated });
    }, [taskId]);
    const toggleDodItem = useCallback((index) => saveDod(
        dodRef.current.map((item, i) => i === index ? { ...item, checked: !item.checked } : item)), [saveDod]);
    const addDodItem = useCallback(async () => {
        const text = newDodRef.current.trim();
        if (!text) return;
        setNewDodText('');
        await saveDod([...dodRef.current, { text, checked: false }]);
    }, [saveDod]);
    const removeDodItem = useCallback((index) => saveDod(
        dodRef.current.filter((_, i) => i !== index)), [saveDod]);

    // The composer owns the text and clears itself when this resolves.
    const handleComment = useCallback(async (text) => {
        await api.addComment(taskId, { comment: text });
        const actData = await api.getActivity(taskId);
        setActivities(prev => keepSameActivity(prev, actData));
    }, [taskId]);

    if (loading) return <div className="p-8 text-text-secondary">Loading task...</div>;
    if (!task) return <div className="p-8 text-red-400">Task not found.</div>;

    const runStatus = run ? (RUN_STATUS[run.status] || { bg: '#5f6368', label: run.status }) : null;

    return (
        <div className="flex-1 bg-bg-app overflow-y-auto">
            <Breadcrumbs entity="task" data={task} />
            <div className="max-w-[1700px] mx-auto px-6 pb-5">
                {/* Title and tabs stay put while the page scrolls to the
                    discussion, so you never lose track of which task you're in. */}
                <div data-testid="task-page-header" className="sticky top-0 z-20 bg-bg-app pt-5 pb-5">
                {/* Header */}
                <div className="flex items-start justify-between gap-4 mb-4">
                    {isEditing ? (
                        <TitleEditor
                            aria-label="Title"
                            className="flex-1 text-xl font-bold text-text-primary bg-bg-card border border-border-subtle rounded-lg px-3 py-1.5 focus:outline-none focus:border-accent-primary"
                            initial={formData.title}
                            onDraft={onTitleDraft}
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
                <div className="flex gap-1 border-b border-border-subtle">
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
                </div>

                {tab === 'plan' && (
                    <PlanTab
                        task={task}
                        isEditing={isEditing}
                        epics={epics}
                        saveField={saveField}
                        formData={formData}
                        setFormData={setFormData}
                        profiles={profiles}
                        priorityColors={PRIORITY_COLORS}
                        dodItems={dodItems}
                        newDodText={newDodText}
                        setNewDodText={setNewDodText}
                        toggleDodItem={toggleDodItem}
                        addDodItem={addDodItem}
                        removeDodItem={removeDodItem}
                        projectRepos={projectRepos}
                        commits={commits}
                        draft={draft}
                        commentDraft={commentDraft}
                        taskId={taskId}
                        user={user}
                        onComment={handleComment}
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
                        canRunWithAgent={profiles.some(p => p.account_type === 'agentira_agent' && p.name === task.assignee)}
                        scheduling={scheduling}
                        handleRunWithAgent={handleRunWithAgent}
                    />
                )}

                {tab === 'activity' && <ActivityTab activities={activities} />}
            </div>

            {showCreate && (
                <CreateTaskModal
                    projectId={task.project_id}
                    members={profiles}
                    epics={epics}
                    projectName={projects.find(p => p.id === task.project_id)?.name || ''}
                    onClose={() => setShowCreate(false)}
                    onCreated={() => setShowCreate(false)}
                />
            )}
        </div>
    );
}
