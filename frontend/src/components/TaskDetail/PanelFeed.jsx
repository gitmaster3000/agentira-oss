import React, { useState, useRef } from 'react';
import { Trash2, Plus, FileText } from 'lucide-react';
import { api } from '../../api';

const ATTACHMENT_KIND_OPTIONS = [
    ['other', 'General file'],
    ['test-report', 'Test report'],
    ['recording', 'Recording'],
    ['screenshot', 'Screenshot'],
    ['build', 'Build'],
];
const EVIDENCE_KINDS = new Set(['test-report', 'recording', 'screenshot']);
const attachmentKindLabel = (kind) => (
    ATTACHMENT_KIND_OPTIONS.find(([value]) => value === kind)?.[1] || 'General file'
);

export function initials(name) {
    if (!name) return '?';
    return name.slice(0, 2).toUpperCase();
}
export function relTime(value) {
    if (!value) return '';
    const diff = Math.round((Date.now() - new Date(value).getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return new Date(value).toLocaleDateString();
}

// The feeds below are memoized: they re-render only when their data changes,
// not when the panel re-renders for a keystroke or an unchanged poll.

export const CommentThread = React.memo(function CommentThread({ comments }) {
    return (
                <div className="flex flex-col" style={{ gap: 13 }}>
                    {comments.length === 0 && <p style={{ fontSize: 12 }} className="text-text-tertiary italic">No comments yet.</p>}
                    {comments.map(c => (
                        <div key={c.id} className="flex" style={{ gap: 9 }}>
                            <span style={{ width: 26, height: 26, borderRadius: '50%', flexShrink: 0, background: 'rgba(201,184,255,.16)', color: 'var(--brand-lavender)', fontSize: 9.5, fontWeight: 700 }} className="flex items-center justify-center">{initials(c.actor)}</span>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center" style={{ gap: 7, marginBottom: 3 }}>
                                    <span style={{ fontSize: 12, fontWeight: 600 }} className="text-text-primary">{c.actor}</span>
                                    <span style={{ fontSize: 10 }} className="text-text-tertiary">{relTime(c.created_at)}</span>
                                </div>
                                <div className="text-text-secondary" style={{ fontSize: 12.5, lineHeight: 1.55, background: 'var(--bg-card)', borderRadius: 10, borderTopLeftRadius: 3, padding: '9px 11px' }}>{c.detail}</div>
                            </div>
                        </div>
                    ))}
                </div>

    );
});

export const ActivityTimeline = React.memo(function ActivityTimeline({ activities }) {
    return (
                <div className="flex flex-col">
                    {activities.map((a, i) => (
                        <div key={a.id} className="flex" style={{ gap: 11 }}>
                            <div className="flex flex-col items-center">
                                <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#00bcd4', marginTop: 3 }} />
                                {i < activities.length - 1 && <span className="flex-1" style={{ width: 1.5, background: 'var(--border-subtle)' }} />}
                            </div>
                            <div style={{ paddingBottom: 16 }}>
                                <div style={{ fontSize: 12.5, lineHeight: 1.45 }} className="text-text-primary">
                                    <b>{a.actor}</b> <span className="text-accent-primary">{a.action}</span> {a.detail}
                                </div>
                                <div style={{ fontSize: 10.5, marginTop: 2 }} className="text-text-tertiary">{relTime(a.created_at)} ago</div>
                            </div>
                        </div>
                    ))}
                </div>

    );
});

// Files card: owns the picked attachment kind and the hidden file input.
export const PanelFiles = React.memo(function PanelFiles({ taskId, attachments, onChanged }) {
    const [attachmentKind, setAttachmentKind] = useState('other');
    const fileInputRef = useRef(null);
    const attachmentGroups = [
        { label: 'Test evidence', items: attachments.filter((item) => EVIDENCE_KINDS.has(item.kind)) },
        { label: 'Other files', items: attachments.filter((item) => !EVIDENCE_KINDS.has(item.kind)) },
    ].filter((group) => group.items.length > 0);

    const handleUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try {
            await api.uploadAttachment(taskId, file, attachmentKind);
            onChanged();
        }
        catch (err) { alert(err.message); }
        finally { e.target.value = ''; }
    };
    const handleDelete = async (id, filename) => {
        if (!confirm(`Delete attachment "${filename}"?`)) return;
        try { await api.deleteAttachment(id); onChanged(); }
        catch (err) { alert(err.message); }
    };

    return (
                    <div className="flex flex-col" style={{ gap: 8 }}>
                        {attachmentGroups.map((group) => (
                            <div key={group.label} className="flex flex-col" style={{ gap: 6 }}>
                                <div className="text-text-tertiary uppercase" style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em' }}>
                                    {group.label}
                                </div>
                                {group.items.map(att => (
                            <div key={att.id} className="flex items-center group hover:border-border-strong transition-colors" style={{ gap: 10, padding: '10px 12px', borderRadius: 9, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}>
                                <button type="button"
                                   onClick={() => api.downloadAttachment(att.id, att.filename || att.name).catch(err => alert('Failed to download: ' + err.message))}
                                   className="flex items-center min-w-0 flex-1" style={{ gap: 10, textAlign: 'left', cursor: 'pointer' }}>
                                    <FileText className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--brand-teal)' }} />
                                    <div className="flex-1 min-w-0">
                                        <div style={{ fontSize: 12.5 }} className="text-text-primary truncate">{att.filename || att.name}</div>
                                        <div style={{ fontSize: 10.5 }} className="text-text-tertiary">{attachmentKindLabel(att.kind)}</div>
                                        {att.size != null && <div style={{ fontSize: 10.5 }} className="text-text-tertiary">{Math.round(att.size / 1024)} KB</div>}
                                    </div>
                                </button>
                                <button type="button"
                                   onClick={() => handleDelete(att.id, att.filename || att.name)}
                                   title="Delete attachment"
                                   className="flex-shrink-0 opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all">
                                    <Trash2 className="w-3.5 h-3.5" />
                                </button>
                            </div>
                                ))}
                            </div>
                        ))}
                        <div className="flex items-center" style={{ gap: 6, marginTop: 4 }}>
                            <select
                                aria-label="Attachment kind"
                                className="input"
                                style={{ fontSize: 11.5, padding: '8px 9px' }}
                                value={attachmentKind}
                                onChange={(event) => setAttachmentKind(event.target.value)}
                            >
                                {ATTACHMENT_KIND_OPTIONS.map(([value, label]) => (
                                    <option key={value} value={value}>{label}</option>
                                ))}
                            </select>
                        <button onClick={() => fileInputRef.current?.click()} className="flex flex-1 items-center justify-center text-text-tertiary hover:text-text-secondary transition-colors" style={{ gap: 6, padding: 10, borderRadius: 9, border: '1px dashed var(--border-subtle)', fontSize: 11.5 }}>
                            <Plus className="w-3 h-3" /> Attach a file
                        </button>
                        </div>
                        <input ref={fileInputRef} type="file" className="hidden" onChange={handleUpload} />
                    </div>

    );
});

export function SectionLabel({ children, inline }) {
    return (
        <div style={{ fontSize: 12.5, fontWeight: 800, letterSpacing: '.06em', color: 'var(--text-bright)', marginBottom: inline ? 0 : 11, textTransform: 'uppercase' }}>
            {children}
        </div>
    );
}
