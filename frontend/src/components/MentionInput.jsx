import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api';

/**
 * A single-line comment input with @mention autocomplete over a project's
 * members (humans + agents). Typing "@" opens a filtered picker; Enter/Tab or
 * click inserts "@Name ". Enter (with the menu closed) submits via onSubmit.
 *
 * Inserting the full name (spaces and all) is fine — the backend matches an
 * @mention against the agent's name with spaces stripped (AP-184), so
 * "@Frontend Developer" wakes the "Frontend Developer" agent.
 */
export function MentionInput({
    value,
    onChange,
    onSubmit,
    projectId,
    placeholder = 'Add a comment…',
    className = '',
    menuAbove = false,
    multiline = false,
    rows = 3,
}) {
    const [members, setMembers] = useState([]);
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState('');
    const [active, setActive] = useState(0);
    const inputRef = useRef(null);

    useEffect(() => {
        let alive = true;
        if (!projectId) { setMembers([]); return; }
        api.getProjectMembers(projectId)
            .then(list => { if (alive) setMembers(Array.isArray(list) ? list : []); })
            .catch(() => { if (alive) setMembers([]); });
        return () => { alive = false; };
    }, [projectId]);

    const candidates = members
        .map(m => (typeof m === 'string' ? { name: m } : m))
        .filter(m => {
            const n = (m.name || '').toLowerCase();
            const q = query.toLowerCase();
            return !q || n.includes(q) || n.replace(/\s+/g, '').includes(q.replace(/\s+/g, ''));
        })
        .slice(0, 6);

    // The @token immediately before the caret (start-of-string or whitespace,
    // then "@", then word/.- chars). null when the caret isn't in a mention.
    const tokenBeforeCaret = (text, caret) => {
        const m = text.slice(0, caret).match(/(?:^|\s)@([\w.-]*)$/);
        return m ? m[1] : null;
    };

    const handleChange = (e) => {
        const text = e.target.value;
        onChange(text);
        const tok = tokenBeforeCaret(text, e.target.selectionStart ?? text.length);
        if (tok !== null) { setQuery(tok); setOpen(true); setActive(0); }
        else { setOpen(false); }
    };

    const insert = (name) => {
        const el = inputRef.current;
        const caret = el ? (el.selectionStart ?? value.length) : value.length;
        const before = value.slice(0, caret).replace(/@([\w.-]*)$/, `@${name} `);
        const after = value.slice(caret);
        onChange(before + after);
        setOpen(false);
        requestAnimationFrame(() => {
            if (el) { el.focus(); el.setSelectionRange(before.length, before.length); }
        });
    };

    const handleKeyDown = (e) => {
        if (open && candidates.length) {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive(i => (i + 1) % candidates.length); return; }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive(i => (i - 1 + candidates.length) % candidates.length); return; }
            if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insert(candidates[active].name); return; }
            if (e.key === 'Escape') { e.preventDefault(); setOpen(false); return; }
        }
        // Single-line inputs submit on Enter; multiline textareas keep Enter
        // for newlines (a button submits) so mentions can span lines freely.
        if (!multiline && e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            onSubmit?.();
        }
    };

    const commonProps = {
        ref: inputRef,
        value,
        onChange: handleChange,
        onKeyDown: handleKeyDown,
        onBlur: () => setTimeout(() => setOpen(false), 120),
        placeholder,
        className,
    };

    return (
        <div className="relative">
            {multiline
                ? <textarea {...commonProps} rows={rows} />
                : <input {...commonProps} />}
            {open && candidates.length > 0 && (
                <div
                    className={`absolute z-50 left-0 w-64 max-h-56 overflow-auto rounded-lg border border-border-subtle bg-bg-panel shadow-lg py-1 ${menuAbove ? 'bottom-full mb-1' : 'top-full mt-1'}`}
                >
                    {candidates.map((m, i) => (
                        <button
                            key={m.name}
                            type="button"
                            onMouseDown={(e) => { e.preventDefault(); insert(m.name); }}
                            className={`w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm transition-colors ${i === active ? 'bg-bg-hover' : 'hover:bg-bg-hover'}`}
                        >
                            <span className="w-5 h-5 rounded bg-accent-subtle text-accent-primary text-[10px] font-bold flex items-center justify-center shrink-0">
                                {(m.name || '?')[0].toUpperCase()}
                            </span>
                            <span className="text-text-primary truncate">@{m.name}</span>
                            {m.role && <span className="ml-auto text-[10px] text-text-tertiary capitalize shrink-0">{m.role}</span>}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
