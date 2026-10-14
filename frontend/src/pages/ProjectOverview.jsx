/**
 * Project Overview — the landing tab of a project (mockup: home-dashboard.html).
 *
 * Main column: description, four rings (Done / Open / Due this week / Late)
 * with a one-line summary, Milestones and epics, Recent activity.
 * Right column: About (key, lead, repository, started, Edit details) and
 * People with roles (Lead / Agent / Member) + Add people.
 *
 * Board, members, epics and the recent activity feed come from ProjectLayout
 * via outlet context. The page makes two requests of its own: milestones and
 * the project attachments list (inside <ProjectAttachments>).
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useParams, Link, useOutletContext, useNavigate } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Markdown } from '../components/Markdown';
import { UserAvatar } from '../components/UserAvatar';
import { ProjectAttachments } from '../components/ProjectAttachments';

const TEAL = 'var(--status-done)';
const LAV = 'var(--accent-primary)';
const AMBER = 'var(--warn-amber)';
const CORAL = 'var(--late-coral)';
const DAY = 86400000;
const MAX_ITEMS = 5;
const ACTIVITY_SHOWN = 8;
const BTN = 'inline-flex items-center border rounded-lg px-3 py-1.5 text-[12.5px] text-text-secondary hover:text-text-primary transition-colors';

function timeAgo(iso) {
    if (!iso) return '';
    // Activity timestamps are naive UTC; append Z so they parse as UTC.
    const then = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    const s = Math.floor((Date.now() - then.getTime()) / 1000);
    if (isNaN(s)) return '';
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    if (s < 604800) return `${Math.floor(s / 86400)}d ago`;
    return then.toLocaleDateString();
}



// A task is "open" until it lands in the done column.
function summarize(board, epics, milestones) {
    const cols = board?.columns || {};
    const done = (cols.done || []).length;
    const openTasks = Object.entries(cols).filter(([k]) => k !== 'done').flatMap(([, v]) => v);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const weekEnd = today.getTime() + 7 * DAY;
    let due = 0; let late = 0;
    const lateByEpic = {};
    for (const t of openTasks) {
        if (!t.due_date) continue;
        const ms = new Date(t.due_date).getTime();
        if (ms < today.getTime()) { late += 1; if (t.epic_id) lateByEpic[t.epic_id] = true; }
        else if (ms < weekEnd) due += 1;
    }
    const doneByEpic = {}; const totalByEpic = {};
    for (const [col, list] of Object.entries(cols)) {
        for (const t of list) {
            if (!t.epic_id) continue;
            totalByEpic[t.epic_id] = (totalByEpic[t.epic_id] || 0) + 1;
            if (col === 'done') doneByEpic[t.epic_id] = (doneByEpic[t.epic_id] || 0) + 1;
        }
    }
    const all = [
        ...(milestones || []).filter((m) => m.status !== 'done').map((m) => {
            const ms = m.due_date ? new Date(m.due_date).getTime() : null;
            const atRisk = m.progress < 100 && ms != null
                && (ms < today.getTime() || (ms < today.getTime() + 14 * DAY && m.progress < 50));
            return {
                key: `m-${m.id}`, title: m.title, progress: m.progress, atRisk, dueMs: ms,
                sub: atRisk && ms < today.getTime() ? 'Overdue'
                    : m.due_date ? `${m.done} of ${m.total} done · due ${new Date(m.due_date).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`
                        : `${m.done} of ${m.total} done`,
                atRiskLabel: atRisk,
            };
        }),
        ...(epics || []).filter((e) => e.status !== 'done' && totalByEpic[e.id]).map((e) => {
            const d = doneByEpic[e.id] || 0; const n = totalByEpic[e.id];
            const atRisk = !!lateByEpic[e.id];
            return {
                key: `e-${e.id}`, title: e.title, progress: Math.round((d / n) * 100), atRisk,
                sub: `${atRisk ? 'Has late tasks · ' : ''}${d} of ${n} done`, epicId: e.id,
            };
        }),
    ];
    // At most 5: at-risk / overdue first, then in progress, then due soonest.
    const rank = (it) => (it.atRisk ? 0 : it.progress > 0 ? 1 : 2);
    const items = all
        .sort((x, y) => rank(x) - rank(y) || (x.dueMs ?? Infinity) - (y.dueMs ?? Infinity))
        .slice(0, MAX_ITEMS);
    return { done, open: openTasks.length, total: done + openTasks.length, due, late, items, hidden: all.length - items.length };
}


function Ring({ value, of, color, label }) {
    const r = 40; const C = 2 * Math.PI * r;
    const frac = of > 0 ? Math.min(value, of) / of : 0;
    return (
        <figure className="m-0 flex flex-col items-center gap-1.5">
            <svg viewBox="0 0 96 96" width="96" height="96" role="img" aria-label={`${label}: ${value}`}>
                <circle cx="48" cy="48" r={r} fill="none" stroke="var(--border-subtle)" strokeWidth="8" />
                <circle cx="48" cy="48" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
                    strokeDasharray={`${C * frac} ${C}`} transform="rotate(-90 48 48)" />
                <text x="48" y="55" textAnchor="middle" fontSize="22" fontWeight="600" fill="var(--text-primary)">{value}</text>
            </svg>
            <figcaption className="text-[13px] font-semibold text-text-secondary">{label}</figcaption>
        </figure>
    );
}


function Panel({ children, className = '' }) {
    return <div className={`rounded-2xl border bg-bg-panel p-4 ${className}`}>{children}</div>;
}


function SectionTitle({ children, first }) {
    return <h3 className={`text-[15px] font-semibold text-text-primary mb-2.5 ${first ? '' : 'mt-6'}`}>{children}</h3>;
}


function ProgressRow({ item }) {
    const color = item.atRisk ? AMBER : LAV;
    const title = item.epicId
        ? <Link to={ROUTES.STUDIO_EPIC(item.epicId)} className="font-semibold text-text-primary hover:text-accent-primary flex-1 truncate">{item.title}</Link>
        : <b className="font-semibold text-text-primary flex-1 truncate">{item.title}</b>;
    return (
        <div className="py-2">
            <div className="flex gap-2 items-baseline">
                {title}
                <span className="text-[12.5px] shrink-0" style={{ color: item.atRisk ? AMBER : 'var(--text-tertiary)' }}>
                    {item.atRisk ? 'At risk · ' : ''}{item.sub}
                </span>
            </div>
            <div className="h-1.5 rounded-full bg-bg-app overflow-hidden mt-1.5"
                role="progressbar" aria-label={item.title} aria-valuenow={item.progress} aria-valuemin={0} aria-valuemax={100}>
                <span className="block h-full rounded-full" style={{ width: `${item.progress}%`, background: color }} />
            </div>
        </div>
    );
}


function roleOf(m, leadName) {
    if (m.name === leadName) return 'Lead';
    return m.account_type && m.account_type !== 'human' ? 'Agent' : 'Member';
}


function PeopleCard({ members, leadName, availableProfiles, onAddMember }) {
    const [adding, setAdding] = useState(false);
    const [query, setQuery] = useState('');
    const q = query.trim().toLowerCase();
    const matches = q
        ? (availableProfiles || []).filter((p) => [p.name, p.display_name]
            .some((v) => (v || '').toLowerCase().includes(q))).slice(0, 6)
        : [];
    return (
        <Panel>
            {members.length === 0 && <div className="text-xs text-text-tertiary pb-2">No members yet.</div>}
            {members.map((m) => (
                <div key={m.id || m.name} className="flex items-center gap-3 py-2 border-b last:border-b-0 min-w-0">
                    <UserAvatar profile={m} size={28} />
                    <span className="flex-1 min-w-0 truncate text-sm text-text-primary">{m.display_name || m.name}</span>
                    <span className="text-[12.5px] text-text-tertiary shrink-0">{roleOf(m, leadName)}</span>
                </div>
            ))}
            {adding ? (
                <div className="mt-2.5">
                    <input type="text" autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search by name…" aria-label="Search people to add"
                        className="input w-full" style={{ padding: '6px 10px', fontSize: 12.5 }} />
                    {q && matches.length === 0 && (
                        <div className="px-1 py-2 text-xs text-text-tertiary">No one matches “{query.trim()}”.</div>
                    )}
                    {matches.map((p) => (
                        <button key={p.id} type="button"
                            onClick={() => { onAddMember(p.name); setQuery(''); setAdding(false); }}
                            className="w-full flex items-center gap-2.5 px-1 py-1.5 rounded-lg hover:bg-bg-hover text-left">
                            <UserAvatar profile={p} size={24} />
                            <span className="flex-1 truncate text-sm text-text-primary">{p.display_name || p.name}</span>
                            <Plus className="w-3.5 h-3.5 text-text-tertiary" />
                        </button>
                    ))}
                </div>
            ) : (
                <button type="button" onClick={() => setAdding(true)} className={`${BTN} mt-2.5`}>Add people</button>
            )}
        </Panel>
    );
}


export function ProjectOverview() {
    const { projectId } = useParams();
    const navigate = useNavigate();
    const { board, members = [], epics = [], activity = [], availableProfiles, onAddMember } = useOutletContext() || {};
    const [milestones, setMilestones] = useState([]);

    useEffect(() => {
        let alive = true;
        api.listMilestones(projectId)
            .then((m) => { if (alive) setMilestones(m || []); })
            .catch(() => {});
        return () => { alive = false; };
    }, [projectId]);

    const stats = useMemo(() => summarize(board, epics, milestones), [board, epics, milestones]);

    const project = board?.project;
    if (!project) return <div className="p-8 text-text-secondary">Project not found.</div>;

    const lead = members.find((m) => (m.roles || [m.role]).includes('admin') && m.account_type === 'human')
        || members.find((m) => m.account_type === 'human') || members[0];
    const repo = (project.repo_url || project.repo_path || '').replace(/\.git$/, '').split('/').filter(Boolean).pop();
    const pct = stats.total ? Math.round((stats.done / stats.total) * 100) : 0;
    const summary = stats.total === 0
        ? 'No tasks yet.'
        : `${pct}% of ${stats.total} tasks done. ${stats.late
            ? `${stats.late} ${stats.late === 1 ? 'task is' : 'tasks are'} late, and`
            : 'Nothing is late, and'} ${stats.due} ${stats.due === 1 ? 'is' : 'are'} due this week.`;

    return (
        <div className="h-full overflow-y-auto">
            <div className="max-w-6xl mx-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px] gap-7">
                <section className="min-w-0">
                    {project.description ? (
                        <div className="mb-5 text-base leading-relaxed text-text-secondary max-w-[62ch]"><Markdown>{project.description}</Markdown></div>
                    ) : (
                        <p className="mb-5 text-text-tertiary">No description yet.</p>
                    )}
                    <div className="flex flex-wrap gap-6">
                        <Ring value={stats.done} of={stats.total} color={TEAL} label="Done" />
                        <Ring value={stats.open} of={stats.total} color={LAV} label="Open" />
                        <Ring value={stats.due} of={Math.max(stats.open, 1)} color={AMBER} label="Due this week" />
                        <Ring value={stats.late} of={Math.max(stats.open, 1)} color={CORAL} label="Late" />
                    </div>
                    <p className="mt-3.5 mb-1 text-[15px] text-text-secondary max-w-[60ch]">{summary}</p>

                    <SectionTitle>Milestones and epics</SectionTitle>
                    <Panel>
                        {stats.items.length === 0
                            ? <div className="text-xs text-text-tertiary py-1">No milestones or epics with tasks yet.</div>
                            : stats.items.map((it) => <ProgressRow key={it.key} item={it} />)}
                        <Link to={`${ROUTES.STUDIO_PROJECT(projectId)}/epics`}
                            className="inline-block mt-2 text-[13px] text-accent-primary hover:underline">
                            See all epics{stats.hidden > 0 ? ` (${stats.hidden} more)` : ''}
                        </Link>
                    </Panel>

                    <SectionTitle>Recent activity</SectionTitle>
                    <Panel>
                        <RecentActivity activity={activity} board={board} members={members} />
                    </Panel>

                    <SectionTitle>Attachments</SectionTitle>
                    <Panel><ProjectAttachments projectId={projectId} /></Panel>
                </section>

                <aside className="min-w-0">
                    <SectionTitle first>About</SectionTitle>
                    <Panel>
                        <dl className="grid grid-cols-[90px_1fr] gap-x-2.5 gap-y-1.5 m-0 text-[13px]">
                            <dt className="text-text-tertiary">Key</dt><dd className="m-0">{project.key_prefix}</dd>
                            <dt className="text-text-tertiary">Lead</dt><dd className="m-0">{lead ? (lead.display_name || lead.name) : '—'}</dd>
                            <dt className="text-text-tertiary">Repository</dt><dd className="m-0 truncate">{repo || '—'}</dd>
                            <dt className="text-text-tertiary">Started</dt>
                            <dd className="m-0">{project.created_at ? new Date(project.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}</dd>
                        </dl>
                        <button type="button" className={`${BTN} mt-3`}
                            onClick={() => navigate(ROUTES.STUDIO_PROJECT_SETTINGS(projectId))}>Edit details</button>
                    </Panel>
                    <SectionTitle>People</SectionTitle>
                    <PeopleCard members={members} leadName={lead?.name}
                        availableProfiles={availableProfiles} onAddMember={onAddMember} />
                </aside>
            </div>
        </div>
    );
}


// Maps a raw activity `action` to a human verb.
const ACTION_VERB = {
    commented: 'commented on',
    'task.create': 'created',
    'task.move': 'moved',
    'task.update': 'updated',
};

// One line of plain text: first line of the body, markdown/link syntax stripped.
function oneLine(text) {
    return String(text || '')
        .split('\n').map((l) => l.trim()).find(Boolean)
        ?.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/[*_`#>]/g, '')
        .trim() || '';
}


// One row per event (mockup): avatar, "actor verb", one ellipsised line with
// the task key + title, and the time. Comment text is cut to one line; the
// full text stays on the task. Key/title come from the board ProjectLayout
// already loaded, so no extra request.
function ActivityRow({ entry, task, profile }) {
    const actor = entry.actor || 'system';
    const verb = ACTION_VERB[entry.action] || entry.action || 'did something to';
    const label = task ? `${task.key} ${task.title}` : `#${String(entry.task_id || '').slice(0, 8)}`;
    const snippet = oneLine(entry.detail);
    return (
        <div className="grid grid-cols-[30px_minmax(0,1fr)_auto] gap-3 items-start py-2.5">
            <UserAvatar profile={profile} name={actor} size={30} />
            <div className="min-w-0">
                <div className="text-sm text-text-secondary"><b className="font-semibold text-text-primary">{actor}</b> {verb}</div>
                {entry.task_id && (
                    <Link to={ROUTES.STUDIO_TASK(entry.task_id)} title={task?.title}
                        className="block truncate text-[12.5px] text-text-tertiary hover:text-accent-primary">
                        {label}
                    </Link>
                )}
                {snippet && <div className="truncate text-[12.5px] text-text-tertiary">{snippet}</div>}
            </div>
            <time className="text-xs text-text-tertiary whitespace-nowrap">{timeAgo(entry.created_at)}</time>
        </div>
    );
}


function RecentActivity({ activity, board, members }) {
    const [all, setAll] = useState(false);
    const tasksById = useMemo(() => {
        const m = {};
        for (const list of Object.values(board?.columns || {})) for (const t of list) m[t.id] = t;
        return m;
    }, [board]);
    if (activity.length === 0) return <div className="text-xs text-text-tertiary py-1">Nothing yet.</div>;
    const shown = all ? activity : activity.slice(0, ACTIVITY_SHOWN);
    return (
        <>
            <div className="divide-y divide-border-subtle/60">
                {shown.map((a, i) => <ActivityRow key={a.id || i} entry={a} task={tasksById[a.task_id]}
                    profile={members.find((m) => m.name === a.actor || m.display_name === a.actor)} />)}
            </div>
            {activity.length > ACTIVITY_SHOWN && (
                <button type="button" onClick={() => setAll((v) => !v)}
                    className="mt-1 text-[13px] text-accent-primary hover:underline">
                    {all ? 'Show less' : 'See all activity'}
                </button>
            )}
        </>
    );
}
