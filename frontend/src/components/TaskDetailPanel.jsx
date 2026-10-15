import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { Markdown } from './Markdown';
import { CommentComposer } from './TaskDetail/CommentComposer';
import { TitleEditor, DescriptionEditor } from './TaskDetail/TextDraft';
import { CommentThread, ActivityTimeline, PanelFiles, SectionLabel } from './TaskDetail/PanelFeed';
import { PanelHeader } from './TaskDetail/PanelHeader';
import { PanelRuns } from './TaskDetail/PanelRuns';
import { PanelFields } from './TaskDetail/PanelFields';
import { PanelDod } from './TaskDetail/PanelDod';
import { PanelGit } from './TaskDetail/PanelGit';
import { usePanelData, usePanelWidth } from './TaskDetail/usePanelData';
import { LinksSection } from './TaskDetail/LinksSection';
import { CollapsibleSection } from './TaskDetail/CollapsibleSection';
import { TestedBy } from './TaskDetail/TestedBy';
import {
    FileText, GitBranch, Info, ListTree, MessageSquare, Activity as ActivityIcon,
} from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';

const RAIL = [
    { id: 'info', label: 'Details', icon: Info },
    { id: 'relations', label: 'Links', icon: ListTree },
    { id: 'files', label: 'Files', icon: FileText },
    { id: 'git', label: 'Branch & PR', icon: GitBranch },
    { id: 'comments', label: 'Comments', icon: MessageSquare },
    { id: 'activity', label: 'Activity', icon: ActivityIcon },
];

// `members` and `epics` come from ProjectLayout, which already holds them, so
// the Assignee and Epic dropdowns are filled on the first frame.
export function TaskDetailPanel({ task, members = [], epics = [], onClose, onUpdate, onSelectTask, isEditing, setIsEditing }) {
    const { user } = useAuth();
    const { activities, attachments, commits, taskRuns, loadActivity, loadAttachments, loadTaskRuns } = usePanelData(task.id);
    const { width, startResize } = usePanelWidth();
    const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
    const [formData, setFormData] = useState({ ...task });
    const [activeSection, setActiveSection] = useState('info');
    const [openSections, setOpenSections] = useState(() =>
        Object.fromEntries(RAIL.map(({ id }) => [id, true])));

    const scrollRef = useRef(null);
    const sectionRefs = useRef({});
    // Drafts (title, description, branch, PR link, comment) live in their own
    // inputs and report here by ref, so typing never re-renders the panel. The
    // inputs reseed from these refs if their section is collapsed and reopened,
    // so what Save writes is always what the user sees.
    const draft = useRef({});
    const commentDraft = useRef('');
    const onTitleDraft = useCallback(v => { draft.current.title = v; }, []);

    // ProjectLayout keys the panel by task id, so every task starts with fresh
    // refs and form state; only the parent-owned edit flag needs clearing.
    useEffect(() => { setIsEditing(false); }, [setIsEditing]);

    const startEditing = () => { draft.current = {}; setFormData({ ...task }); setIsEditing(true); };
    const cancelEditing = () => { draft.current = {}; setIsEditing(false); setFormData({ ...task }); };
    const handleSave = async () => {
        try {
            // Edit mode edits everything, including Branch & PR.
            await api.updateTask(task.id, {
                title: draft.current.title ?? formData.title,
                description: draft.current.description ?? formData.description,
                branch: draft.current.branch ?? formData.branch ?? '',
                pr_url: draft.current.pr_url ?? formData.pr_url ?? '',
            });
            setIsEditing(false);
            onUpdate();
        } catch (err) { alert(err.message); }
    };

    // Status/priority/assignee are inline-editable (no edit mode) — save on change.
    const saveField = async (patch) => {
        try { await api.updateTask(task.id, patch); onUpdate(); }
        catch (err) { alert(err.message); }
    };
    const saveStatus = async (s) => {
        if (s === task.status) return;
        // Dedicated /move endpoint drives transitions/activity.
        try { await api.moveTask(task.id, s); onUpdate(); }
        catch (err) { alert(err.message); }
    };
    // The composer owns the text and clears itself when this resolves.
    const handleComment = async (text) => {
        await api.addComment(task.id, { comment: text });
        loadActivity();
    };
    const handleDelete = async () => {
        try { await api.deleteTask(task.id); onUpdate(); }
        catch (err) { alert(err.message); setIsConfirmingDelete(false); }
    };
    const onFilesChanged = () => { loadAttachments(); loadActivity(); };

    // Measure section offsets via getBoundingClientRect so the math is
    // independent of offsetParent (the scroll container isn't positioned).
    const scrollTo = (id) => {
        setOpenSections(prev => ({ ...prev, [id]: true }));
        const el = sectionRefs.current[id];
        const c = scrollRef.current;
        if (el && c) {
            const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop - 12;
            c.scrollTo({ top, behavior: 'smooth' });
        }
        setActiveSection(id);
    };
    const toggleSection = (id) => {
        setOpenSections(prev => ({ ...prev, [id]: !prev[id] }));
        setActiveSection(id);
    };
    const onScroll = () => {
        const c = scrollRef.current;
        if (!c) return;
        const cTop = c.getBoundingClientRect().top;
        let current = 'info';
        for (const { id } of RAIL) {
            const el = sectionRefs.current[id];
            if (el && el.getBoundingClientRect().top - cTop <= 28) current = id;
        }
        setActiveSection(current);
    };

    const comments = useMemo(() => activities.filter(a => a.action === 'commented'), [activities]);
    const section = (id, title, icon, props = {}) => ({
        title,
        icon,
        sectionRef: el => (sectionRefs.current[id] = el),
        open: openSections[id],
        onToggle: () => toggleSection(id),
        ...props,
    });

    return (
        <aside
            className="h-full flex flex-col flex-shrink-0 animate-slide-in relative"
            style={{ width, background: 'var(--bg-panel)', borderLeft: '1px solid var(--border-subtle)' }}
            onClick={e => e.stopPropagation()}
        >
            <div
                role="separator"
                aria-label="Resize panel"
                aria-orientation="vertical"
                onMouseDown={startResize}
                className="absolute top-0 left-0 h-full hover:bg-accent-primary/30 transition-colors"
                style={{ width: 6, marginLeft: -3, cursor: 'col-resize', zIndex: 10 }}
            />
            <PanelHeader
                task={task}
                isEditing={isEditing}
                onSave={handleSave}
                onCancel={cancelEditing}
                onEdit={startEditing}
                onDelete={() => setIsConfirmingDelete(true)}
                onClose={onClose}
            />

            {/* Title */}
            <div style={{ padding: '15px 18px 13px' }}>
                {isEditing ? (
                    <TitleEditor
                        className="w-full bg-bg-app border border-border-subtle rounded-lg p-2 text-text-primary focus:outline-none focus:border-accent-primary"
                        style={{ fontSize: 17.5, fontWeight: 600 }}
                        initial={formData.title}
                        onDraft={onTitleDraft}
                        maxLength={255}
                        autoFocus
                    />
                ) : (
                    // Clamp to 3 lines so a long title can't push the divider below
                    // out of alignment; full title stays available on hover.
                    <h2
                        title={task.title}
                        style={{ fontSize: 17.5, fontWeight: 600, margin: 0, lineHeight: 1.3, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                        className="text-text-primary"
                    >
                        {task.title}
                    </h2>
                )}
            </div>

            <div className="flex-1 flex min-h-0" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                {/* Icon rail */}
                <nav className="flex flex-col items-center flex-shrink-0" style={{ width: 50, borderRight: '1px solid var(--border-subtle)', gap: 4, padding: '10px 0' }}>
                    {RAIL.map(({ id, label, icon: Icon }) => {
                        const active = activeSection === id;
                        return (
                            <button
                                key={id}
                                onClick={() => scrollTo(id)}
                                title={label}
                                className="flex items-center justify-center transition-colors"
                                style={{
                                    width: 34, height: 34, borderRadius: 8,
                                    color: active ? 'var(--brand-lavender)' : 'var(--text-muted)',
                                    background: active ? 'rgba(201,184,255,.12)' : 'transparent',
                                }}
                            >
                                <Icon className="w-4 h-4" />
                            </button>
                        );
                    })}
                </nav>

                {/* Scroll body */}
                <div ref={scrollRef} onScroll={onScroll} className="flex-1 min-w-0 overflow-y-auto custom-scrollbar" style={{ padding: '16px 18px', position: 'relative', scrollBehavior: 'smooth' }}>
                    <CollapsibleSection {...section('info', 'Details', Info)}>
                        <PanelRuns task={task} members={members} taskRuns={taskRuns} onRunsChanged={loadTaskRuns} />
                        <PanelFields task={task} members={members} epics={epics} saveStatus={saveStatus} saveField={saveField} />

                        {/* Description reads after the at-a-glance fields — the
                            fields are the scannable part, the prose is the detail. */}
                        <SectionLabel>Description</SectionLabel>
                        {isEditing ? (
                            <DescriptionEditor
                                className="w-full bg-bg-app border border-border-subtle rounded-lg p-2.5 text-text-secondary focus:outline-none focus:border-accent-primary"
                                style={{ fontSize: 12.5, lineHeight: 1.6, minHeight: 90, marginBottom: 18 }}
                                initial={draft.current.description ?? formData.description}
                                onDraft={v => { draft.current.description = v; }}
                            />
                        ) : (
                            <div style={{ fontSize: 12.5, lineHeight: 1.6, marginBottom: 18 }} className="text-text-tertiary break-words">
                                {task.description ? <Markdown>{task.description}</Markdown> : <span className="italic">No description.</span>}
                            </div>
                        )}

                        <PanelDod task={task} onUpdate={onUpdate} />
                        <div style={{ marginBottom: 18 }}>
                            <TestedBy taskId={task.id} refreshKey={attachments} />
                        </div>
                    </CollapsibleSection>

                    {/* Links share the full-page component. Adding one works
                        anywhere; removing one needs Edit. */}
                    <CollapsibleSection {...section('relations', 'Links', ListTree, { separated: true })}>
                        <LinksSection task={task} onChanged={onUpdate} onOpenTask={onSelectTask} isEditing={isEditing} compact />
                    </CollapsibleSection>

                    <CollapsibleSection {...section('files', 'Files', FileText, { separated: true })}>
                        <PanelFiles taskId={task.id} attachments={attachments} onChanged={onFilesChanged} />
                    </CollapsibleSection>

                    <CollapsibleSection {...section('git', 'Branch & PR', GitBranch, { separated: true })}>
                        <PanelGit task={task} commits={commits} isEditing={isEditing} draft={draft} onSaved={onUpdate} />
                    </CollapsibleSection>

                    <CollapsibleSection {...section('comments', 'Comments', MessageSquare, { separated: true })}>
                        {/* Composer sits ABOVE the thread so it's the first thing
                            you reach, and grows with what you type. */}
                        <CommentComposer
                            key={task.id}
                            variant="panel"
                            user={user}
                            projectId={task.project_id}
                            members={members}
                            onSubmit={handleComment}
                            draftRef={commentDraft}
                        />
                        <CommentThread comments={comments} />
                    </CollapsibleSection>

                    <CollapsibleSection {...section('activity', 'Activity', ActivityIcon, { separated: true })}>
                        <ActivityTimeline activities={activities} />
                    </CollapsibleSection>
                    <div style={{ height: 80 }} />
                </div>
            </div>

            {isConfirmingDelete && (
                <ConfirmModal
                    title="Delete Task"
                    message={`Are you sure you want to delete task "${task.title}"?`}
                    confirmText="Delete"
                    onConfirm={handleDelete}
                    onCancel={() => setIsConfirmingDelete(false)}
                />
            )}
        </aside>
    );
}
