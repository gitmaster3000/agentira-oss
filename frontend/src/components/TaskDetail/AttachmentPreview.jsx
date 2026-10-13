import React, { useEffect, useState } from 'react';
import { Download, X, Loader2 } from 'lucide-react';
import { api } from '../../api';
import { Markdown } from '../Markdown';

// Extension -> how to show it and the MIME type we force on the blob. We never
// trust the server's content type for rendering: HTML/JS must stay inert.
const TYPES = {
    png: ['image', 'image/png'], jpg: ['image', 'image/jpeg'], jpeg: ['image', 'image/jpeg'],
    gif: ['image', 'image/gif'], webp: ['image', 'image/webp'], svg: ['image', 'image/svg+xml'],
    pdf: ['pdf', 'application/pdf'],
    md: ['markdown', 'text/plain'], markdown: ['markdown', 'text/plain'],
    txt: ['text', 'text/plain'], log: ['text', 'text/plain'], json: ['text', 'text/plain'],
};
const MAX_TEXT_BYTES = 1024 * 1024;

const extOf = (filename) => filename?.split('.').pop()?.toLowerCase();
export const previewKind = (filename) => TYPES[extOf(filename)]?.[0] || null;

export function AttachmentPreview({ attachment, onClose, onDownload }) {
    const kind = previewKind(attachment.filename);
    const [url, setUrl] = useState(null);
    const [text, setText] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        let objectUrl;
        let cancelled = false;
        api.fetchAttachmentBlob(attachment.id).then(async (blob) => {
            if (cancelled) return;
            if (kind === 'markdown' || kind === 'text') {
                if (blob.size > MAX_TEXT_BYTES) throw new Error('File too large to preview — download it instead.');
                setText(await blob.text());
                return;
            }
            const typed = new Blob([blob], { type: TYPES[extOf(attachment.filename)][1] });
            objectUrl = URL.createObjectURL(typed);
            setUrl(objectUrl);
        }).catch((err) => { if (!cancelled) setError(err.message); });
        return () => {
            cancelled = true;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [attachment.id]);

    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    const loading = !error && url === null && text === null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
            <div
                role="dialog"
                aria-label={`Preview ${attachment.filename}`}
                className="bg-bg-panel border border-border-subtle rounded-lg w-full max-w-5xl h-[85vh] flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between px-4 py-2 border-b border-border-subtle">
                    <div className="text-sm font-medium text-text-primary truncate">{attachment.filename}</div>
                    <div className="flex items-center gap-1 shrink-0">
                        <button onClick={onDownload} className="p-1.5 text-text-tertiary hover:text-accent-primary rounded-md" title="Download">
                            <Download className="w-4 h-4" />
                        </button>
                        <button onClick={onClose} className="p-1.5 text-text-tertiary hover:text-text-primary rounded-md" title="Close">
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                </div>
                <div className="flex-1 overflow-auto p-4 flex items-center justify-center">
                    {error && <div className="text-sm text-red-400">{error}</div>}
                    {loading && <Loader2 className="w-5 h-5 animate-spin text-text-tertiary" />}
                    {url && kind === 'image' && (
                        <img src={url} alt={attachment.filename} className="max-w-full max-h-full object-contain" />
                    )}
                    {url && kind === 'pdf' && (
                        <iframe src={url} title={attachment.filename} className="w-full h-full border-0" />
                    )}
                    {text !== null && kind === 'markdown' && (
                        <div className="w-full h-full self-start"><Markdown>{text}</Markdown></div>
                    )}
                    {text !== null && kind === 'text' && (
                        <pre className="w-full h-full self-start text-xs text-text-secondary whitespace-pre-wrap break-words">{text}</pre>
                    )}
                </div>
            </div>
        </div>
    );
}

export default AttachmentPreview;
