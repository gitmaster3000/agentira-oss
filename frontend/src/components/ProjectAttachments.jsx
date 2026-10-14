/**
 * Project attachments (AP-152) — drag-and-drop upload, list, download, delete.
 * Lives in project Settings. Fetches only when mounted, i.e. when the
 * Attachments section is opened, so no other page pays for it.
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Upload, FileText, Trash2, Download } from 'lucide-react';
import { api } from '../api';

function formatSize(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ProjectAttachments({ projectId }) {
    const [attachments, setAttachments] = useState([]);
    const reload = useCallback(async () => {
        try {
            setAttachments((await api.listProjectAttachments(projectId)) || []);
        } catch { /* keep prior */ }
    }, [projectId]);
    useEffect(() => { reload(); }, [reload]);
    return <AttachmentsList projectId={projectId} attachments={attachments} onChange={reload} />;
}

function AttachmentsList({ projectId, attachments, onChange }) {
    const fileInputRef = useRef(null);
    const [dragActive, setDragActive] = useState(false);
    const [uploading, setUploading] = useState(false);

    const uploadFiles = async (fileList) => {
        const files = Array.from(fileList || []);
        if (!files.length) return;
        setUploading(true);
        try {
            for (const f of files) {
                await api.uploadProjectAttachment(projectId, f);
            }
            await onChange();
        } catch (err) {
            alert('Upload failed: ' + (err.message || err));
        } finally {
            setUploading(false);
        }
    };

    const handleDelete = async (att) => {
        if (!window.confirm(`Delete ${att.filename}?`)) return;
        try {
            await api.deleteAttachment(att.id);
            await onChange();
        } catch (err) {
            alert('Delete failed: ' + (err.message || err));
        }
    };

    return (
        <div className="space-y-3">
            <div
                className="rounded-lg p-4 text-center cursor-pointer transition-all"
                style={{
                    border: `2px dashed ${dragActive ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                    backgroundColor: dragActive ? 'var(--accent-subtle)' : 'var(--bg-app)',
                }}
                onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDrop={(e) => { e.preventDefault(); setDragActive(false); uploadFiles(e.dataTransfer.files); }}
                onClick={() => fileInputRef.current?.click()}
            >
                <Upload className="w-5 h-5 mx-auto mb-1.5" style={{ color: dragActive ? 'var(--accent-primary)' : 'var(--text-tertiary)' }} />
                <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                    {uploading
                        ? 'Uploading…'
                        : <>Drop files here or <span style={{ color: 'var(--accent-primary)', fontWeight: 600 }}>click to browse</span></>}
                </p>
                <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-tertiary)' }}>
                    Briefs, designs, brand guides — agents can read text inline; binary fetched on demand.
                </p>
                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(e) => { uploadFiles(e.target.files); e.target.value = ''; }}
                />
            </div>
            {attachments.length > 0 && (
                <div className="space-y-1">
                    {attachments.map((a) => (
                        <div key={a.id}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs"
                            style={{ backgroundColor: 'var(--bg-panel)', border: '1px solid var(--border-subtle)' }}
                        >
                            <FileText className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--accent-primary)' }} />
                            <span className="flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{a.filename}</span>
                            <span className="flex-shrink-0" style={{ color: 'var(--text-tertiary)' }}>{formatSize(a.size_bytes)}</span>
                            <button
                                type="button"
                                onClick={() => api.downloadAttachment(a.id, a.filename).catch(err => alert('Failed to download: ' + err.message))}
                                className="p-0.5 rounded-lg hover:bg-bg-hover"
                                style={{ color: 'var(--text-tertiary)' }}
                                title="Download"
                            >
                                <Download className="w-3 h-3" />
                            </button>
                            <button
                                type="button"
                                onClick={() => handleDelete(a)}
                                className="p-0.5 rounded-lg hover:bg-red-500/10 transition-colors"
                                style={{ color: 'var(--text-tertiary)' }}
                                title="Delete"
                            >
                                <Trash2 className="w-3 h-3" />
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
