import React, { useState, useRef } from 'react';
import { Send } from 'lucide-react';
import { MentionInput } from '../MentionInput';

/**
 * Comment box that owns its own draft, so typing re-renders only this
 * component, never the page or panel around it. The text leaves only on
 * submit: `onSubmit(text)` posts it, and the draft clears when that resolves
 * (unless more was typed meanwhile).
 *
 * The parent can pass `draftRef` (a `useRef('')`) so the text survives this
 * component unmounting, e.g. when its section is collapsed or the tab changes.
 *
 * variant "page" is the full task page box; "panel" is the compact side-panel
 * one with the round send button.
 */
export function CommentComposer({ variant = 'page', user, projectId, members, onSubmit, draftRef }) {
    const ownRef = useRef('');
    const store = draftRef || ownRef;
    const [value, setValueState] = useState(store.current);
    const setValue = (v) => { store.current = v; setValueState(v); };

    const submit = async (e) => {
        if (e) e.preventDefault();
        const sent = value;
        if (!sent.trim()) return;
        try {
            await onSubmit(sent);
            // Keep anything typed while the POST was in flight.
            if (store.current === sent) setValue('');
        } catch (err) {
            alert(err.message);
        }
    };
    const initial = user?.display_name?.[0]?.toUpperCase() || 'U';

    if (variant === 'panel') {
        const canSend = !!value.trim();
        return (
            <form onSubmit={submit} className="flex items-end" style={{ gap: 8, marginBottom: 16 }}>
                <span style={{ width: 26, height: 26, borderRadius: '50%', flexShrink: 0, background: 'var(--bg-card)', color: 'var(--text-tertiary)', fontSize: 9.5, fontWeight: 700 }} className="flex items-center justify-center">{initial}</span>
                <div className="flex-1 min-w-0" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '6px 10px' }}>
                    <MentionInput
                        multiline
                        autoGrow
                        rows={2}
                        className="block w-full bg-transparent text-text-primary text-xs leading-relaxed focus:outline-none resize-none max-h-32 overflow-y-auto"
                        placeholder="Comment or @mention…  (Shift+Enter for a new line)"
                        value={value}
                        onChange={setValue}
                        onSubmit={submit}
                        projectId={projectId}
                        members={members}
                    />
                </div>
                <button
                    type="submit"
                    disabled={!canSend}
                    title="Send comment"
                    className="flex items-center justify-center flex-shrink-0 transition-colors"
                    style={{
                        width: 32, height: 32, borderRadius: '50%',
                        background: canSend ? 'var(--accent-primary)' : 'var(--bg-card)',
                        color: canSend ? 'var(--accent-on)' : 'var(--text-tertiary)',
                        border: '1px solid var(--border-subtle)',
                        cursor: canSend ? 'pointer' : 'not-allowed',
                    }}
                >
                    <Send className="w-3.5 h-3.5" />
                </button>
            </form>
        );
    }

    return (
        <div className="flex gap-4 mb-8">
            <div className="w-10 h-10 rounded-full bg-accent-subtle flex items-center justify-center font-bold text-sm text-accent-primary flex-shrink-0">
                {initial}
            </div>
            <form onSubmit={submit} className="flex-1">
                <MentionInput
                    multiline
                    rows={3}
                    className="w-full bg-bg-card border border-border-subtle text-sm p-4 rounded-lg focus:outline-none focus:border-accent-primary transition-colors h-24 resize-none shadow-sm"
                    placeholder="Add a comment… (@ to mention an agent)"
                    value={value}
                    onChange={setValue}
                    onSubmit={submit}
                    projectId={projectId}
                    members={members}
                />
                <div className="mt-2 flex justify-end">
                    <button className="btn btn-primary">Add Comment</button>
                </div>
            </form>
        </div>
    );
}
