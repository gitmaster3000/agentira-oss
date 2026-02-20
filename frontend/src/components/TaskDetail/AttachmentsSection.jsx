import React, { useState, useEffect, useRef } from 'react';
import { api } from '../../api';
import { useAuth } from '../../context/AuthContext';
import { Paperclip, Download, Trash2, File as FileIcon, Loader2, Image as ImageIcon, FileText } from 'lucide-react';
import { ConfirmModal } from '../ConfirmModal';

export function AttachmentsSection({ taskId }) {
    const { user } = useAuth();
    const [attachments, setAttachments] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isUploading, setIsUploading] = useState(false);
    const [attachmentToDelete, setAttachmentToDelete] = useState(null);
    const fileInputRef = useRef(null);

    const loadAttachments = async () => {
        setIsLoading(true);
        try {
            const data = await api.listAttachments(taskId);
            setAttachments(data || []);
        } catch (err) {
            console.error('[AttachmentsSection] Error loading attachments:', err);
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        if (taskId) {
            loadAttachments();
        }
    }, [taskId]);

    const handleFileSelect = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setIsUploading(true);
        try {
            await api.uploadAttachment(taskId, file);
            await loadAttachments();
        } catch (err) {
            console.error('[AttachmentsSection] Upload failed:', err);
            alert('Failed to upload file: ' + err.message);
        } finally {
            setIsUploading(false);
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        }
    };

    const handleDelete = async () => {
        if (!attachmentToDelete) return;

        try {
            await api.deleteAttachment(attachmentToDelete.id);
            setAttachments(prev => prev.filter(a => a.id !== attachmentToDelete.id));
        } catch (err) {
            console.error('[AttachmentsSection] Delete failed:', err);
            alert('Failed to delete attachment: ' + err.message);
        } finally {
            setAttachmentToDelete(null);
        }
    };

    const formatSize = (bytes) => {
        if (!bytes) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    };

    const getFileIcon = (filename) => {
        const ext = filename?.split('.').pop()?.toLowerCase();
        if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return <ImageIcon className="w-5 h-5 text-accent-primary" />;
        if (['pdf', 'doc', 'docx', 'txt', 'md'].includes(ext)) return <FileText className="w-5 h-5 text-blue-400" />;
        return <FileIcon className="w-5 h-5 text-text-secondary" />;
    };

    return (
        <div className="mt-6 border-t border-border-subtle pt-6">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                    <Paperclip className="w-4 h-4" /> Attachments
                </h3>
                <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileSelect}
                    className="hidden"
                />
                <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading}
                    className="btn btn-ghost py-1 px-3 text-xs"
                >
                    {isUploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Upload File'}
                </button>
            </div>

            {isLoading ? (
                <div className="py-4 text-center text-text-tertiary text-xs">Loading attachments...</div>
            ) : attachments.length === 0 ? (
                <div className="py-8 text-center bg-bg-app rounded-md border border-border-subtle border-dashed">
                    <p className="text-xs text-text-tertiary mb-2">No attachments yet</p>
                    <button
                        onClick={() => fileInputRef.current?.click()}
                        className="text-xs text-accent-primary hover:underline"
                    >
                        Upload a file
                    </button>
                </div>
            ) : (
                <div className="space-y-2">
                    {attachments.map(attachment => (
                        <div
                            key={attachment.id}
                            className="flex items-center justify-between p-3 bg-bg-app rounded-md border border-border-subtle hover:border-border-active group transition-colors"
                        >
                            <div className="flex items-center gap-3 min-w-0">
                                <div className="p-2 bg-bg-panel rounded-md shrink-0">
                                    {getFileIcon(attachment.filename)}
                                </div>
                                <div className="min-w-0">
                                    <div className="text-sm text-text-primary font-medium truncate" title={attachment.filename}>
                                        {attachment.filename}
                                    </div>
                                    <div className="text-xs text-text-tertiary flex items-center gap-2">
                                        <span>{formatSize(attachment.size_bytes)}</span>
                                        <span>•</span>
                                        <span>{attachment.uploaded_by}</span>
                                        <span>•</span>
                                        <span title={new Date(attachment.created_at).toLocaleString()}>
                                            {new Date(attachment.created_at).toLocaleDateString()}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-2">
                                <a
                                    href={api.getAttachmentDownloadUrl?.(attachment.id) || `${api.API_BASE}/attachments/${attachment.id}/download`}
                                    download={attachment.filename}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="p-1.5 text-text-tertiary hover:text-accent-primary hover:bg-bg-hover rounded-md transition-colors"
                                    title="Download"
                                >
                                    <Download className="w-4 h-4" />
                                </a>
                                <button
                                    onClick={() => setAttachmentToDelete(attachment)}
                                    className="p-1.5 text-text-tertiary hover:text-red-400 hover:bg-red-500/10 rounded-md transition-colors"
                                    title="Delete"
                                >
                                    <Trash2 className="w-4 h-4" />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {!!attachmentToDelete && (
                <ConfirmModal
                    onCancel={() => setAttachmentToDelete(null)}
                    onConfirm={handleDelete}
                    title="Delete Attachment"
                    message={`Are you sure you want to delete "${attachmentToDelete?.filename}"? This action cannot be undone.`}
                    confirmText="Delete Attachment"
                    isDanger={true}
                />
            )}
        </div>
    );
}

export default AttachmentsSection;
