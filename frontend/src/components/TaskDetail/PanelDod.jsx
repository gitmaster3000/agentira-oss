import React, { useState } from 'react';
import { Check, Plus, X } from 'lucide-react';
import { api } from '../../api';
import { SectionLabel } from './PanelFeed';

// Definition-of-Done list. Owns its items and the "Add item" draft, so typing
// there re-renders only this list. The panel is keyed by task id, so a task
// switch remounts it with that task's items.
export function PanelDod({ task, onUpdate }) {
    const [items, setItems] = useState(task.dod_items || []);
    const [newText, setNewText] = useState('');

    const save = async (updated) => {
        setItems(updated);
        try { await api.updateTask(task.id, { dod_items: updated }); onUpdate(); } catch (err) { console.error(err); }
    };
    const toggle = (index) => save(items.map((item, i) => i === index ? { ...item, checked: !item.checked } : item));
    const remove = (index) => save(items.filter((_, i) => i !== index));
    const add = () => {
        if (!newText.trim()) return;
        const text = newText.trim();
        setNewText('');
        save([...items, { text, checked: false }]);
    };
    const doneCount = items.filter(i => i.checked).length;

    return (
        <>
            <div className="flex items-center justify-between" style={{ marginBottom: 9 }}>
                <SectionLabel inline>Definition of Done</SectionLabel>
                {items.length > 0 && <span style={{ fontSize: 11 }} className="text-text-tertiary">{doneCount} / {items.length}</span>}
            </div>
            {items.map((item, i) => (
                <div key={i} className="flex items-center group" style={{ gap: 9, fontSize: 12.5, marginBottom: 6 }}>
                    <button onClick={() => toggle(i)} className="flex-shrink-0 flex items-center justify-center" style={{ width: 16, height: 16, borderRadius: 5, background: item.checked ? '#2ecc71' : 'transparent', border: item.checked ? 'none' : '1.5px solid var(--border-strong, var(--border-strong))' }}>
                        {item.checked && <Check className="w-2.5 h-2.5" style={{ color: 'var(--surface-base)' }} strokeWidth={3} />}
                    </button>
                    <span className="flex-1" style={item.checked ? { color: 'var(--text-muted)', textDecoration: 'line-through' } : { color: 'var(--text-bright)' }}>{item.text}</span>
                    <button onClick={() => remove(i)} className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-red-400 transition-all"><X className="w-3 h-3" /></button>
                </div>
            ))}
            <div className="flex items-center" style={{ gap: 6, marginTop: 4, marginBottom: 18 }}>
                <input
                    className="flex-1 bg-bg-app border border-border-subtle rounded text-text-primary focus:outline-none focus:border-accent-primary"
                    style={{ fontSize: 12, padding: '5px 8px' }}
                    placeholder="Add item…"
                    value={newText}
                    onChange={e => setNewText(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && add()}
                />
                <button onClick={add} className="text-text-tertiary hover:text-accent-primary"><Plus className="w-4 h-4" /></button>
            </div>
        </>
    );
}
