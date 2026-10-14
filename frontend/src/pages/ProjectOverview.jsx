/**
 * Project Overview — the landing tab of a project (mockup: home-dashboard.html).
 *
 * Main column: description, four rings (Done / Open / Due this week / Late)
 * with a one-line summary, Milestones and epics, Recent activity.
 * Right column: About (key, lead, repository, started, Edit details) and
 * People with roles (Lead / Agent / Member) + Add people.
 *
 * No data of its own except milestones: board, members, epics and the recent
 * activity feed all come from ProjectLayout via outlet context. Milestones is
 * the single extra request this page makes.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useParams, Link, useOutletContext, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Activity, MessageSquare, Plus, ArrowRight, Pencil, ArrowUpRight } from 'lucide-react';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Markdown } from '../components/Markdown';
import { UserAvatar } from '../components/UserAvatar';

const TEAL = 'var(--status-done)';
const LAV = 'var(--accent-primary)';
const AMBER = 'var(--warn-amber)';
const CORAL = 'var(--late-coral)';
const DAY = 86400000;
const MAX_ITEMS = 5;
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
                        {activity.length === 0 ? (
                            <div className="text-xs text-text-tertiary py-1">Nothing yet.</div>
                        ) : (
                            <div className="divide-y divide-border-subtle/60">
                                {activity.map((a, i) => <ActivityRow key={a.id || i} entry={a} />)}
                            </div>
                        )}
                    </Panel>
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


// Maps a raw activity `action` to an icon, accent color, and human label.
const ACTION_META = {
    commented:     { icon: MessageSquare, color: '#7c4dff', label: 'commented' },
    'task.create': { icon: Plus,          color: '#2ecc71', label: 'created task' },
    'task.move':   { icon: ArrowRight,    color: '#00bcd4', label: 'moved task' },
    'task.update': { icon: Pencil,        color: '#f1c40f', label: 'updated task' },
};

function actionMeta(action) {
    return ACTION_META[action] || { icon: Activity, color: '#9aa0a6', label: action || 'activity' };
}


// SPA-aware link: internal app paths route through react-router (no full
// reload); external URLs open in a new tab. Used for links embedded in
// activity details (e.g. run links like /forge/runs/<id> and PR URLs).
function SmartLink({ href, children, ...rest }) {
    const isInternal = typeof href === 'string' && href.startsWith('/');
    if (isInternal) {
        return (
            <Link to={href} className="text-accent-primary hover:underline" {...rest}>
                {children}
            </Link>
        );
    }
    return (
        <a href={href} target="_blank" rel="noopener noreferrer"
            className="text-accent-primary hover:underline" {...rest}>
            {children}
        </a>
    );
}

// Compact markdown for activity details — tight spacing, clickable links.
const FEED_MD_COMPONENTS = {
    a: ({ node, ...p }) => <SmartLink {...p} />,
    p: (p) => <p className="text-sm text-text-secondary leading-snug my-0.5" {...p} />,
    ul: (p) => <ul className="list-disc pl-5 my-1 text-sm text-text-secondary space-y-0.5" {...p} />,
    ol: (p) => <ol className="list-decimal pl-5 my-1 text-sm text-text-secondary space-y-0.5" {...p} />,
    li: (p) => <li className="text-sm text-text-secondary" {...p} />,
    strong: (p) => <strong className="text-text-primary font-semibold" {...p} />,
    em: (p) => <em className="italic" {...p} />,
    code: (p) => <code className="px-1 py-0.5 rounded bg-bg-panel text-xs font-mono text-text-primary" {...p} />,
    h1: (p) => <p className="text-sm font-semibold text-text-primary my-0.5" {...p} />,
    h2: (p) => <p className="text-sm font-semibold text-text-primary my-0.5" {...p} />,
    h3: (p) => <p className="text-sm font-semibold text-text-primary my-0.5" {...p} />,
};


function ActivityRow({ entry, projectId }) {
    const meta = actionMeta(entry.action);
    const Icon = meta.icon;
    const actor = entry.actor || 'system';
    return (
        <div className="flex gap-3 px-2 py-2.5 rounded-md hover:bg-bg-hover/50 transition-colors">
            <div className="w-7 h-7 rounded-full bg-accent-subtle flex items-center justify-center text-xs font-bold text-accent-primary border border-accent-primary/20 flex-shrink-0">
                {actor[0]?.toUpperCase() || 'S'}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap text-xs">
                    <span className="font-semibold text-text-primary">{actor}</span>
                    <span className="inline-flex items-center gap-1 text-text-secondary">
                        <Icon className="w-3 h-3" style={{ color: meta.color }} />
                        {meta.label}
                    </span>
                    <span className="text-text-tertiary">· {timeAgo(entry.created_at)}</span>
                    {entry.task_id && (
                        <Link
                            to={ROUTES.STUDIO_TASK(entry.task_id)}
                            className="ml-auto inline-flex items-center gap-0.5 text-text-tertiary hover:text-accent-primary transition-colors"
                            title="Open task"
                        >
                            #{String(entry.task_id).slice(0, 8)}
                            <ArrowUpRight className="w-3 h-3" />
                        </Link>
                    )}
                </div>
                {entry.detail && (
                    <div className="mt-1">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={FEED_MD_COMPONENTS}>
                            {String(entry.detail)}
                        </ReactMarkdown>
                    </div>
                )}
            </div>
        </div>
    );
}


