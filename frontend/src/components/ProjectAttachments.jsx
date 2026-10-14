/**
 * Project attachments (AP-152) — drag-and-drop upload, list, download, delete.
 * Rendered on the project Overview; makes its own single request (the list).
 * Same behaviour as before the Overview redesign, restyled to match the
 * Overview panels.
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
    const fileInputRef = useRef(null);
    const [attachments, setAttachments] = useState([]);
    const [dragActive, setDragActive] = useState(false);
    const [uploading, setUploading] = useState(false);

    const reload = useCallback(async () => {
        try {
            setAttachments((await api.listProjectAttachments(projectId)) || []);
        } catch { /* keep prior */ }
    }, [projectId]);
    useEffect(() => { reload(); }, [reload]);

    const uploadFiles = async (fileList) => {
        const files = Array.from(fileList || []);
        if (!files.length) return;
        setUploading(true);
        try {
            for (const f of files) {
                await api.uploadProjectAttachment(projectId, f);
            }
            await reload();
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
            await reload();
        } catch (err) {
            alert('Delete failed: ' + (err.message || err));
        }
    };

    return (
        <div className="space-y-3">
            <div
                role="button" tabIndex={0} aria-label="Upload attachments"
                className={`rounded-xl border-2 border-dashed p-4 text-center cursor-pointer transition-colors ${dragActive ? 'border-accent-primary bg-accent-subtle' : 'bg-bg-app'}`}
                onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                onDragLeave={() => setDragActive(false)}
                onDrop={(e) => { e.preventDefault(); setDragActive(false); uploadFiles(e.dataTransfer.files); }}
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => { if (e.key === 'Enter') fileInputRef.current?.click(); }}
            >
                <Upload className={`w-5 h-5 mx-auto mb-1.5 ${dragActive ? 'text-accent-primary' : 'text-text-tertiary'}`} />
                <p className="text-xs text-text-secondary">
                    {uploading
                        ? 'Uploading…'
                        : <>Drop files here or <span className="font-semibold text-accent-primary">click to browse</span></>}
                </p>
                <p className="text-[10px] mt-0.5 text-text-tertiary">
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
                <div className="divide-y divide-border-subtle/60">
                    {attachments.map((a) => (
                        <div key={a.id} className="flex items-center gap-3 py-2 text-[13px] min-w-0">
                            <FileText className="w-4 h-4 flex-shrink-0 text-accent-primary" />
                            <span className="flex-1 truncate text-text-primary">{a.filename}</span>
                            <span className="flex-shrink-0 text-text-tertiary">{formatSize(a.size_bytes)}</span>
                            <button type="button" title="Download" aria-label={`Download ${a.filename}`}
                                onClick={() => api.downloadAttachment(a.id, a.filename).catch((err) => alert('Failed to download: ' + err.message))}
                                className="p-0.5 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-hover">
                                <Download className="w-3.5 h-3.5" />
                            </button>
                            <button type="button" title="Delete" aria-label={`Delete ${a.filename}`}
                                onClick={() => handleDelete(a)}
                                className="p-0.5 rounded-lg text-text-tertiary hover:text-red-400 hover:bg-red-500/10 transition-colors">
                                <Trash2 className="w-3.5 h-3.5" />
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
