import React, { useState, useRef, useCallback } from 'react';
import { api } from '../api';
import { useNavigate } from 'react-router-dom';
import { Briefcase, X, Upload, FileText, Trash2, AlertCircle } from 'lucide-react';

const PROJECT_CATEGORIES = [
    'Software Engineering',
    'Product Management',
    'Marketing',
    'Design',
    'Operations',
    'Research',
    'Other',
];

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CreateProjectModal({ onClose, onSuccess }) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [category, setCategory] = useState('');
    const [loading, setLoading] = useState(false);
    const [files, setFiles] = useState([]);
    const [dragActive, setDragActive] = useState(false);
    const navigate = useNavigate();
    const modalRef = useRef(null);
    const fileInputRef = useRef(null);

    // File handling
    const addFiles = useCallback((newFiles) => {
        const arr = Array.from(newFiles);
        setFiles(prev => {
            const existing = new Set(prev.map(f => f.name + f.size));
            const unique = arr.filter(f => !existing.has(f.name + f.size));
            return [...prev, ...unique];
        });
    }, []);

    const removeFile = (idx) => setFiles(prev => prev.filter((_, i) => i !== idx));

    const handleDrop = (e) => {
        e.preventDefault();
        setDragActive(false);
        if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim()) return;

        setLoading(true);
        try {
            const p = await api.createProject({
                name: name.trim(),
                description: buildDescription(),
            });

            // Upload staged files as attachments to a setup task if files exist
            if (files.length > 0) {
                try {
                    const setupTask = await api.createTask({
                        project_id: p.id,
                        title: '📎 Project Setup Files',
                        description: `Files uploaded during project creation:\n${files.map(f => `- ${f.name}`).join('\n')}`,
                        priority: 'low',
                        status: 'backlog',
                    });
                    for (const file of files) {
                        await api.uploadAttachment(setupTask.id, file);
                    }
                } catch (uploadErr) {
                    console.error('Failed to upload project files:', uploadErr);
                }
            }

            onSuccess();
            navigate(`/board/${p.id}`);
            onClose();
        } catch (err) {
            alert(err.message);
        } finally {
            setLoading(false);
        }
    };

    const buildDescription = () => {
        let desc = description.trim();
        if (category) {
            desc = `**Category:** ${category}\n\n${desc}`;
        }
        return desc;
    };

    // Click outside to close
    const handleBackdropClick = (e) => {
        if (modalRef.current && !modalRef.current.contains(e.target)) {
            onClose();
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in"
            onClick={handleBackdropClick}
        >
            <div
                ref={modalRef}
                className="w-full max-w-lg rounded-xl shadow-2xl overflow-hidden"
                style={{
                    backgroundColor: 'var(--bg-card)',
                    border: '1px solid var(--border-subtle)',
                }}
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div
                    className="px-6 py-5 flex items-center gap-3"
                    style={{ borderBottom: '1px solid var(--border-subtle)' }}
                >
                    <div
                        className="w-10 h-10 rounded-lg flex items-center justify-center shadow-lg flex-shrink-0"
                        style={{ backgroundColor: 'var(--accent-primary)' }}
                    >
                        <Briefcase className="w-5 h-5 text-white" />
                    </div>
                    <div className="flex-1">
                        <h3 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
                            Create New Project
                        </h3>
                        <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                            Set up a workspace for your team
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-xl transition-colors hover:bg-bg-hover"
                        style={{ color: 'var(--text-tertiary)' }}
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[70vh] overflow-y-auto custom-scrollbar">
                    {/* Project Name */}
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Project Name <span style={{ color: '#ef4444' }}>*</span>
                        </label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="input"
                            placeholder="e.g. Website Redesign"
                            autoFocus
                            required
                        />
                    </div>

                    {/* Category */}
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Category
                        </label>
                        <select
                            className="input"
                            value={category}
                            onChange={(e) => setCategory(e.target.value)}
                        >
                            <option value="">Select category...</option>
                            {PROJECT_CATEGORIES.map(c => (
                                <option key={c} value={c}>{c}</option>
                            ))}
                        </select>
                    </div>

                    {/* Description */}
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Description
                        </label>
                        <textarea
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            className="input resize-none h-20"
                            placeholder="What's this project about?"
                        />
                    </div>

                    {/* Attachments */}
                    <div>
                        <label className="block text-xs font-bold uppercase mb-1.5" style={{ color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>
                            Attachments
                        </label>
                        <div
                            className="rounded-lg p-4 text-center cursor-pointer transition-all"
                            style={{
                                border: `2px dashed ${dragActive ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                                backgroundColor: dragActive ? 'var(--accent-subtle)' : 'var(--bg-app)',
                            }}
                            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                            onDragLeave={() => setDragActive(false)}
                            onDrop={handleDrop}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            <Upload className="w-5 h-5 mx-auto mb-1.5" style={{ color: dragActive ? 'var(--accent-primary)' : 'var(--text-tertiary)' }} />
                            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                                Drop files here or <span style={{ color: 'var(--accent-primary)', fontWeight: 600 }}>click to browse</span>
                            </p>
                            <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-tertiary)' }}>
                                Specs, briefs, mockups — anything to get started
                            </p>
                            <input
                                ref={fileInputRef}
                                type="file"
                                multiple
                                className="hidden"
                                onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ''; }}
                            />
                        </div>

                        {/* File list */}
                        {files.length > 0 && (
                            <div className="mt-2 space-y-1">
                                {files.map((file, idx) => (
                                    <div
                                        key={`${file.name}-${idx}`}
                                        className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs"
                                        style={{ backgroundColor: 'var(--bg-panel)', border: '1px solid var(--border-subtle)' }}
                                    >
                                        <FileText className="w-3.5 h-3.5 flex-shrink-0" style={{ color: 'var(--accent-primary)' }} />
                                        <span className="flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{file.name}</span>
                                        <span className="flex-shrink-0" style={{ color: 'var(--text-tertiary)' }}>{formatSize(file.size)}</span>
                                        <button
                                            type="button"
                                            onClick={(e) => { e.stopPropagation(); removeFile(idx); }}
                                            className="p-0.5 rounded-lg hover:bg-red-500/10 transition-colors"
                                            style={{ color: 'var(--text-tertiary)' }}
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </button>
                                    </div>
                                ))}
                                <div className="flex items-center gap-1 mt-1 px-1">
                                    <AlertCircle className="w-3 h-3" style={{ color: 'var(--text-tertiary)' }} />
                                    <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>
                                        Files will be attached to a setup task in the project
                                    </span>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Actions */}
                    <div className="flex justify-end gap-2 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                        <button type="button" onClick={onClose} className="btn btn-ghost">
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={loading || !name.trim()}
                            className="btn btn-primary"
                        >
                            {loading ? 'Creating...' : 'Create Project'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
