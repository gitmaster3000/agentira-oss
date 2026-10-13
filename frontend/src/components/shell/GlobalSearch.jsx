import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { ROUTES } from '../../routes';

// Top-bar search: debounced query to /api/search, grouped results,
// ⌘K / Ctrl+K to focus, ↑/↓ + Enter to open, Esc to close.

const GROUPS = [
    { key: 'tasks', label: 'TASKS', tint: 'rgba(128,203,196,.14)', glyph: '▦',
        title: (r) => r.title, sub: (r) => [r.key, r.project_name].filter(Boolean).join(' · '),
        badge: (r) => r.status, to: (r) => ROUTES.STUDIO_TASK(r.id) },
    { key: 'epics', label: 'EPICS', tint: 'rgba(197,138,249,.14)', glyph: '≡',
        title: (r) => r.title, sub: (r) => `Epic · ${r.project_name}`, to: (r) => ROUTES.STUDIO_EPIC(r.id) },
    { key: 'projects', label: 'PROJECTS', tint: 'rgba(201,184,255,.14)', glyph: '▣',
        title: (r) => r.name, sub: (r) => r.key, to: (r) => ROUTES.STUDIO_PROJECT_BOARD(r.id) },
    { key: 'agents', label: 'AGENTS', tint: 'rgba(56,189,248,.14)', glyph: '◉',
        title: (r) => r.name, sub: (r) => `Agent${r.model ? ` · ${r.model}` : ''}`, to: (r) => ROUTES.FORGE_AGENT(r.id) },
];

function highlight(text, q) {
    const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
    if (i < 0) return text;
    return <>{text.slice(0, i)}<mark style={{ background: 'rgba(201,184,255,.25)', color: 'var(--brand-lavender)', borderRadius: '3px' }}>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

export function GlobalSearch() {
    const navigate = useNavigate();
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [active, setActive] = useState(0);
    const wrapRef = useRef(null);
    const inputRef = useRef(null);

    const term = q.trim();
    const flat = data ? GROUPS.flatMap((g) => (data[g.key] || []).map((r) => ({ g, r }))) : [];

    useEffect(() => {
        if (!term) { setData(null); setLoading(false); return undefined; }
        setLoading(true);
        let cancelled = false;
        const id = setTimeout(async () => {
            try {
                const res = await api.search(term);
                if (!cancelled) { setData(res); setActive(0); }
            } catch {
                if (!cancelled) setData(null);
            } finally {
                if (!cancelled) setLoading(false);
            }
        }, 200);
        return () => { cancelled = true; clearTimeout(id); };
    }, [term]);

    useEffect(() => {
        const onKey = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                inputRef.current?.focus();
            }
        };
        const onDown = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
        document.addEventListener('keydown', onKey);
        document.addEventListener('mousedown', onDown);
        return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDown); };
    }, []);

    const go = ({ g, r }) => {
        setOpen(false);
        setQ('');
        inputRef.current?.blur();
        navigate(g.to(r));
    };

    const onKeyDown = (e) => {
        if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur(); }
        else if (e.key === 'ArrowDown' && flat.length) { e.preventDefault(); setActive((a) => (a + 1) % flat.length); }
        else if (e.key === 'ArrowUp' && flat.length) { e.preventDefault(); setActive((a) => (a - 1 + flat.length) % flat.length); }
        else if (e.key === 'Enter' && flat[active]) { e.preventDefault(); go(flat[active]); }
    };

    const hint = (txt) => <div style={{ padding: '24px 14px', textAlign: 'center', fontSize: '12px', color: 'var(--text-muted)' }}>{txt}</div>;
    let idx = -1;

    return (
        <div ref={wrapRef} style={{ position: 'relative', width: '210px', flexShrink: 0 }}>
            <div className="hoverline" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 11px', borderRadius: '10px', background: 'var(--overlay-tint-soft)', border: `1px solid ${open ? 'var(--brand-lavender)' : 'var(--overlay-line)'}`, color: 'var(--text-muted)' }}>
                <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
                <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => setOpen(true)} onKeyDown={onKeyDown}
                    placeholder="Search or jump…" aria-label="Search"
                    style={{ flex: 1, minWidth: 0, background: 'none', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: '12.5px', fontFamily: 'inherit', padding: 0 }} />
                <span style={{ fontSize: '10px', fontFamily: 'ui-monospace,monospace', background: 'var(--overlay-tint)', border: '1px solid var(--overlay-line)', borderRadius: '6px', padding: '2px 5px', color: 'var(--text-tertiary)' }}>⌘K</span>
            </div>
            {open && (
                <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '420px', maxWidth: '90vw', background: 'var(--surface-card)', border: '1px solid var(--overlay-line)', borderRadius: '14px', boxShadow: 'var(--shadow-popover)', zIndex: 60, overflow: 'hidden', paddingBottom: '5px' }}>
                    {!term ? hint('Type to search tasks, epics, projects and agents.')
                        : loading && !data ? hint('Searching…')
                            : flat.length === 0 ? hint(`No matches for “${term}”.`)
                                : GROUPS.map((g) => {
                                    const rows = (data && data[g.key]) || [];
                                    if (!rows.length) return null;
                                    return (
                                        <div key={g.key}>
                                            <div style={{ fontSize: '9.5px', fontWeight: 700, letterSpacing: '.1em', color: 'var(--text-muted)', padding: '10px 14px 4px' }}>{g.label}</div>
                                            {rows.map((r) => {
                                                idx += 1;
                                                const i = idx;
                                                return (
                                                    <div key={r.id} role="option" aria-selected={i === active} className="nav"
                                                        onMouseEnter={() => setActive(i)} onClick={() => go({ g, r })}
                                                        style={{ display: 'flex', alignItems: 'center', gap: '11px', padding: '8px 10px', margin: '0 5px', borderRadius: '10px', cursor: 'pointer', background: i === active ? 'rgba(201,184,255,.12)' : 'transparent' }}>
                                                        <span style={{ width: '28px', height: '28px', borderRadius: '8px', background: g.tint, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', flexShrink: 0 }}>{g.glyph}</span>
                                                        <div style={{ flex: 1, minWidth: 0 }}>
                                                            <div style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--text-bright)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{highlight(g.title(r), term)}</div>
                                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{g.sub(r)}</div>
                                                        </div>
                                                        {g.badge && g.badge(r) ? <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '999px', border: '1px solid var(--overlay-line)', color: 'var(--text-muted)' }}>{g.badge(r)}</span> : null}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    );
                                })}
                </div>
            )}
        </div>
    );
}
