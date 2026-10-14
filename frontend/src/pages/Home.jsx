import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../context/AuthContext';
import { UserAvatar } from '../components/UserAvatar';
import { CreateProjectWizard } from '../components/CreateProjectWizard';
import { ROUTES } from '../routes';
import './home.css';

const DEFAULT_LAYOUT = [['projects', 'l'], ['activity', 'm'], ['people', 'm']];
const SIZES = [['s', 'Third'], ['m', 'Half'], ['l', 'Full']];
const PROJECTS_SHOWN = 6;

function greeting() {
    const h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
}

function timeAgo(iso) {
    if (!iso) return '';
    const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins} min ago`;
    const h = Math.floor(mins / 60);
    if (h < 24) return `${h} ${h === 1 ? 'hour' : 'hours'} ago`;
    const d = Math.floor(h / 24);
    return `${d} ${d === 1 ? 'day' : 'days'} ago`;
}

const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

const ACTION_VERB = {
    'task.create': 'created',
    'task.move': 'moved',
    'task.comment': 'commented on',
    'task.update': 'updated',
    'task.assign': 'assigned',
};
const verbOf = (action) => ACTION_VERB[action] || action.replace(/^task\./, '').replace(/_/g, ' ');

function WeekRings({ week }) {
    const r = 46;
    const C = 2 * Math.PI * r;
    const rings = [['Done', week.done, 'var(--brand-teal)'], ['Due', week.due, 'var(--warning)'], ['Late', week.late, 'var(--danger)']];
    return (
        <div className="home-rings">
            {rings.map(([label, n, colour], i) => (
                <figure className="home-wr" style={{ '--i': i }} key={label}>
                    <svg viewBox="0 0 110 110" width="110" height="110" role="img" aria-label={`${label}: ${n} of ${week.planned} tasks this week`}>
                        <circle cx="55" cy="55" r={r} fill="none" stroke="var(--surface-card)" strokeWidth="9" />
                        <circle className="home-arc" cx="55" cy="55" r={r} fill="none" stroke={colour} strokeWidth="9" strokeLinecap="round"
                            strokeDasharray={`${week.planned ? C * Math.min(n / week.planned, 1) : 0} ${C}`} transform="rotate(-90 55 55)" />
                        <text x="55" y="61" textAnchor="middle" className="home-rn">{n}</text>
                    </svg>
                    <figcaption>{label}</figcaption>
                </figure>
            ))}
            <p className="home-of">of {plural(week.planned, 'task')} planned this week</p>
        </div>
    );
}

function ProgressRing({ pct, colour }) {
    const r = 17;
    const C = 2 * Math.PI * r;
    return (
        <svg className="home-ring" width="44" height="44" viewBox="0 0 44 44" role="img" aria-label={`${pct}% done`}>
            <circle cx="22" cy="22" r={r} fill="none" stroke="var(--surface-base)" strokeWidth="5" />
            <circle cx="22" cy="22" r={r} fill="none" stroke={colour} strokeWidth="5" strokeLinecap="round"
                strokeDasharray={`${C * pct / 100} ${C}`} transform="rotate(-90 22 22)" />
            <text x="22" y="26" textAnchor="middle">{pct}</text>
        </svg>
    );
}

function ProjectsTile({ data, onNew }) {
    const navigate = useNavigate();
    const [all, setAll] = useState(false);
    const projects = data.projects;
    const shown = all ? projects : projects.slice(0, PROJECTS_SHOWN);
    return (
        <>
            {projects.length === 0 && <div className="home-panel home-empty">No projects yet. Create one to get started.</div>}
            <div className="home-pcards">
                {shown.map((p) => (
                    <button type="button" key={p.id} className="home-pcard" style={{ '--pc': p.colour }} aria-label={`Open ${p.name}`}
                        onClick={() => navigate(ROUTES.STUDIO_PROJECT_OVERVIEW(p.id))}>
                        <div className="home-pc-top">
                            <ProgressRing pct={p.pct_done} colour={p.colour} />
                            <div style={{ minWidth: 0 }}>
                                <div className="name">{p.name}</div>
                                <span className="home-pc-key">{p.key}</span>
                            </div>
                        </div>
                        <p className="home-pc-desc">{p.description}</p>
                        <div className="home-pc-stats">
                            <span><b className="tnum">{p.open}</b> open</span>
                            <span><b className="tnum">{p.due_this_week}</b> due this week</span>
                            {p.late > 0 && <span className="late"><b className="tnum">{p.late}</b> late</span>}
                        </div>
                        <div className="home-pc-foot">
                            <div className="home-stack">
                                {p.members.map((m) => <UserAvatar key={m.id} profile={m} size={28} />)}
                                {p.member_count > p.members.length && <span className="home-more">+{p.member_count - p.members.length}</span>}
                            </div>
                            {p.last_updated && <span className="home-pc-last">Updated {timeAgo(p.last_updated)}</span>}
                        </div>
                    </button>
                ))}
            </div>
            <div style={{ paddingTop: 12 }}>
                {projects.length > PROJECTS_SHOWN && (
                    <button type="button" className="home-btn link" onClick={() => setAll((v) => !v)}>
                        {all ? 'Show fewer' : `All ${projects.length} projects`}
                    </button>
                )}
                <button type="button" className="home-btn link quiet" style={{ marginLeft: 18 }} onClick={onNew}>New project</button>
            </div>
        </>
    );
}

function ActivityTile({ data }) {
    const navigate = useNavigate();
    if (!data.activity.length) return <div className="home-panel home-empty">No recent activity.</div>;
    return (
        <div className="home-panel">
            {data.activity.map((e) => (
                <div className="home-feed" key={e.id}>
                    <UserAvatar name={e.actor} size={30} />
                    <div className="what">
                        <div><b>{e.actor}</b> {verbOf(e.action)}</div>
                        <small>
                            <button type="button" className="home-btn link" style={{ padding: 0, color: 'inherit' }}
                                onClick={() => navigate(ROUTES.STUDIO_PROJECT_BOARD(e.project_id))}>
                                {e.task_key} {e.task_title}
                            </button> in {e.project_name}
                        </small>
                    </div>
                    <time dateTime={e.at}>{timeAgo(e.at)}</time>
                </div>
            ))}
        </div>
    );
}

function PeopleTile({ data }) {
    if (!data.people.length) return <div className="home-panel home-empty">No teammates yet.</div>;
    return (
        <div className="home-panel">
            {data.people.map((p) => (
                <div className="home-person" key={p.name}>
                    <UserAvatar name={p.name} size={30} />
                    <div className="nm">{p.name}</div>
                    <div className="num"><b className="tnum">{p.open}</b>open</div>
                    <div className="home-dots" role="img" aria-label={`${p.days_done_this_week} of 5 days with finished work`}>
                        {[0, 1, 2, 3, 4].map((d) => <i key={d} className={d < p.days_done_this_week ? 'on' : ''} />)}
                    </div>
                </div>
            ))}
        </div>
    );
}

const TILES = {
    projects: { title: 'Projects', sub: (d) => `${d.projects.length} active`, size: 'l', Body: ProjectsTile,
        desc: 'Every project with its description, progress, people and what is due. Click one to open it.' },
    activity: { title: 'Activity', sub: () => 'all projects', size: 'm', Body: ActivityTile,
        desc: 'What changed across your projects: tasks created, moved, finished, commented.' },
    people: { title: 'People', sub: () => 'open now, done this week', size: 'm', Body: PeopleTile,
        desc: 'Everyone on your projects, people and agents alike: what they hold and what they finished.' },
};

const cleanLayout = (l) => (Array.isArray(l) ? l.filter(([id, sz]) => TILES[id] && SIZES.some(([s]) => s === sz)) : []);

export function Home() {
    const { user } = useAuth();
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [layout, setLayout] = useState(DEFAULT_LAYOUT);
    const [editing, setEditing] = useState(false);
    const [catalog, setCatalog] = useState(false);
    const [creating, setCreating] = useState(false);
    const [dragFrom, setDragFrom] = useState(null);
    const [dragOver, setDragOver] = useState(null);

    useEffect(() => {
        let cancelled = false;
        api.getHome().then((d) => !cancelled && setData(d)).catch((e) => !cancelled && setError(e.message || 'Could not load Home'));
        api.getHomeLayout().then((r) => {
            const l = cleanLayout(r?.layout);
            if (!cancelled && l.length) setLayout(l);
        }).catch(() => {});
        return () => { cancelled = true; };
    }, []);

    const update = (next) => {
        setLayout(next);
        api.saveHomeLayout(next).catch(() => {});
    };
    const resize = (i, size) => update(layout.map((t, j) => (j === i ? [t[0], size] : t)));
    const remove = (i) => update(layout.filter((_, j) => j !== i));
    const move = (from, to) => {
        if (to < 0 || to >= layout.length || from === to) return;
        const next = [...layout];
        next.splice(to, 0, next.splice(from, 1)[0]);
        update(next);
    };
    const add = (id) => { update([...layout, [id, TILES[id].size]]); setCatalog(false); };

    if (error) return <div className="home"><div className="home-state" role="alert">{error}</div></div>;
    if (!data) return <div className="home"><div className="home-state">Loading…</div></div>;

    const name = (user?.display_name || user?.name || '').trim();
    const firstName = name ? name.split(/[\s@]/)[0] : null;
    const { week } = data;
    const used = new Set(layout.map(([id]) => id));
    const available = Object.keys(TILES).filter((id) => !used.has(id));

    return (
        <div className={`home${editing ? ' home-editing' : ''}`}>
            <section className="home-week" aria-label="This week">
                <div>
                    <p className="home-greet">{greeting()}{firstName ? `, ${firstName}` : ''}</p>
                    <h1 className="home-sentence">
                        <b className="tnum">{week.done}</b> {week.done === 1 ? 'task' : 'tasks'} done this week.{' '}
                        <b className="tnum">{week.due}</b> due, <b className="tnum late">{week.late}</b> late.
                    </h1>
                    {data.week_summary && <p className="home-summary">{data.week_summary}</p>}
                </div>
                <WeekRings week={week} />
            </section>

            <div className="home-toolbar">
                <h2>Your home</h2><span className="home-grow" />
                {!editing && <button type="button" className="home-btn" onClick={() => setEditing(true)}>Customize</button>}
            </div>
            {editing && (
                <div className="home-editbar">
                    <span>Drag tiles or use the arrows to reorder. Choose a width, or remove a tile.</span><span className="home-grow" />
                    <button type="button" className="home-btn" onClick={() => setCatalog(true)}>Add tile</button>
                    <button type="button" className="home-btn" onClick={() => update(DEFAULT_LAYOUT.map((t) => [...t]))}>Reset to default</button>
                    <button type="button" className="home-btn primary" onClick={() => setEditing(false)}>Done</button>
                </div>
            )}
            {layout.length === 0 && <div className="home-state">Your home is empty. Customize it to add tiles.</div>}
            <div className="home-grid">
                {layout.map(([id, size], i) => {
                    const T = TILES[id];
                    return (
                        <section key={id} className={`home-tile ${size}${dragFrom === i ? ' dragging' : ''}${dragOver === i && dragFrom !== i ? ' over' : ''}`}
                            draggable={editing}
                            onDragStart={() => setDragFrom(i)}
                            onDragEnd={() => { setDragFrom(null); setDragOver(null); }}
                            onDragOver={(e) => { if (editing) { e.preventDefault(); setDragOver(i); } }}
                            onDrop={(e) => { e.preventDefault(); if (dragFrom != null) move(dragFrom, i); setDragFrom(null); setDragOver(null); }}>
                            {editing && (
                                <div className="home-tctl">
                                    <button type="button" aria-label={`Move ${T.title} earlier`} disabled={i === 0} onClick={() => move(i, i - 1)}>↑</button>
                                    <button type="button" aria-label={`Move ${T.title} later`} disabled={i === layout.length - 1} onClick={() => move(i, i + 1)}>↓</button>
                                    {SIZES.map(([s, label]) => (
                                        <button type="button" key={s} className="sz" aria-pressed={size === s} onClick={() => resize(i, s)}>{label}</button>
                                    ))}
                                    <button type="button" aria-label={`Remove ${T.title}`} onClick={() => remove(i)}>Remove</button>
                                </div>
                            )}
                            <h3>{T.title}<small>{T.sub(data)}</small></h3>
                            <T.Body data={data} onNew={() => setCreating(true)} />
                        </section>
                    );
                })}
            </div>

            {catalog && (
                <div className="home-scrim" onClick={() => setCatalog(false)}>
                    <div className="home-modal" role="dialog" aria-label="Add a tile" onClick={(e) => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <h2>Add a tile</h2><span className="home-grow" />
                            <button type="button" className="home-btn" onClick={() => setCatalog(false)}>Close</button>
                        </div>
                        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Pick what you want to see when you open Agentira.</div>
                        <div className="home-cat">
                            {available.length === 0 && <div className="home-empty">Every tile is already on your home.</div>}
                            {available.map((id) => (
                                <div className="home-ci" key={id}>
                                    <b>{TILES[id].title}</b><p>{TILES[id].desc}</p>
                                    <button type="button" className="home-btn" onClick={() => add(id)}>Add</button>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
            {creating && <CreateProjectWizard onClose={() => setCreating(false)} onSuccess={() => setCreating(false)} />}
        </div>
    );
}
