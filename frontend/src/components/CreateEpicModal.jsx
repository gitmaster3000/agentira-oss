import React, { useState } from 'react';
import { api } from '../api';
import { X } from 'lucide-react';

export function CreateEpicModal({ projectId, onClose, onCreated }) {
    const [loading, setLoading] = useState(false);
    const [formData, setFormData] = useState({
        title: '',
        description: '',
        color: '#7c4dff'
    });

    const colors = [
        '#7c4dff', // Deep Purple
        '#00bcd4', // Cyan
        '#2ecc71', // Emerald
        '#f1c40f', // Sunflower
        '#e67e22', // Carrot
        '#e74c3c', // Alizarin
        '#3498db', // Peter River
        '#9b59b6', // Amethyst
    ];

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!formData.title.trim()) return;
        setLoading(true);
        try {
            await api.createEpic(projectId, {
                title: formData.title.trim(),
                description: formData.description.trim(),
                color: formData.color
            });
            if (onCreated) onCreated();
            onClose();
        } catch (err) {
            alert(err.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center animate-fade-in p-4" onClick={onClose}>
            <div
                className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden flex flex-col"
                onClick={e => e.stopPropagation()}
                style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-subtle)' }}
            >
                {/* Header */}
                <div className="px-6 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <h2 className="text-lg font-bold text-text-primary">Create Epic</h2>
                    <button onClick={onClose} className="p-2 rounded-xl hover:bg-bg-hover text-text-tertiary transition-colors">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-5">
                    <div>
                        <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Epic Title</label>
                        <input
                            autoFocus
                            className="input"
                            placeholder="What are we aiming for?"
                            value={formData.title}
                            onChange={e => setFormData({ ...formData, title: e.target.value })}
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Description</label>
                        <textarea
                            className="input resize-none h-24"
                            placeholder="High-level goal or theme..."
                            value={formData.description}
                            onChange={e => setFormData({ ...formData, description: e.target.value })}
                        />
                    </div>

                    <div>
                        <label className="block text-[11px] font-bold uppercase mb-2 text-text-tertiary tracking-wider">Color Theme</label>
                        <div className="flex flex-wrap gap-2.5">
                            {colors.map(c => (
                                <button
                                    key={c}
                                    type="button"
                                    onClick={() => setFormData({ ...formData, color: c })}
                                    className={`w-8 h-8 rounded-full transition-transform hover:scale-110 active:scale-95 flex items-center justify-center ${formData.color === c ? 'ring-2 ring-white ring-offset-2 ring-offset-bg-card' : ''}`}
                                    style={{ backgroundColor: c }}
                                >
                                    {formData.color === c && <div className="w-1.5 h-1.5 rounded-full bg-white shadow-sm" />}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="flex justify-end gap-3 mt-4 pt-5" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                        <button type="button" onClick={onClose} className="btn-ghost px-4 py-2 rounded-xl text-sm font-medium">Cancel</button>
                        <button 
                            type="submit" 
                            disabled={loading || !formData.title.trim()} 
                            className="btn-primary px-6 py-2.5 rounded-xl text-sm font-bold shadow-lg shadow-accent-primary/10 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {loading ? 'Creating...' : 'Create Epic'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
