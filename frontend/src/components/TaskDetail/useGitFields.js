import { useState, useEffect, useRef } from 'react';
import { api } from '../../api';

export function formatBranchDisplay(val) {
    if (!val) return '';
    const treeMatch = val.match(/\/tree\/(.+)$/);
    if (treeMatch) return treeMatch[1];
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

export function formatPrDisplay(val) {
    if (!val) return '';
    const prMatch = val.match(/github\.com\/[^/]+\/([^/]+)\/pull\/(\d+)/);
    if (prMatch) return `${prMatch[1]}#${prMatch[2]}`;
    if (val.startsWith('http')) return val.replace(/^https?:\/\/(www\.)?/, '');
    return val;
}

/**
 * Inline Branch / PR editing shared by the task page card and the side panel.
 * The open field, its draft and the copy tick live here, so typing re-renders
 * only the card. Blur is the single save path (Enter just blurs), so Enter +
 * blur can't save twice. Escape cancels. The edit closes only after a
 * successful save; a failure keeps the draft open and sets `error`.
 */
export function useGitFields(task, onSaved) {
    const [branchValue, setBranchValue] = useState(task.branch || '');
    const [prUrlValue, setPrUrlValue] = useState(task.pr_url || '');
    const [editingBranch, setEditingBranch] = useState(false);
    const [editingPrUrl, setEditingPrUrl] = useState(false);
    const [copiedField, setCopiedField] = useState(null);
    const [error, setError] = useState('');
    const saving = useRef(false);
    const cancelled = useRef(false);

    useEffect(() => { setBranchValue(task.branch || ''); }, [task.branch]);
    useEffect(() => { setPrUrlValue(task.pr_url || ''); }, [task.pr_url]);

    const copyToClipboard = (text, field) => {
        navigator.clipboard.writeText(text);
        setCopiedField(field);
        setTimeout(() => setCopiedField(null), 800);
    };

    const saveField = async (field, val, setEditing) => {
        if (cancelled.current) { cancelled.current = false; return; }
        if (saving.current) return;
        if (val === (task[field] || '')) { setEditing(false); return; }
        saving.current = true;
        try {
            await api.updateTask(task.id, { [field]: val });
            cancelled.current = true; // swallow the blur some browsers fire as the input unmounts
            setEditing(false);
            setError('');
            onSaved();
        } catch (err) {
            setError(err.message || 'Could not save. Try again.');
        } finally {
            saving.current = false;
        }
    };

    // Props for the inline <input> of one field.
    const inputProps = (field, value, setValue, setEditing) => ({
        value,
        onChange: e => setValue(e.target.value),
        onFocus: () => { cancelled.current = false; },
        onBlur: () => saveField(field, value, setEditing),
        onKeyDown: e => {
            if (e.key === 'Enter') e.currentTarget.blur();
            if (e.key === 'Escape') {
                cancelled.current = true;
                setValue(task[field] || '');
                setEditing(false);
                setError('');
            }
        },
        autoFocus: true,
    });

    return {
        branch: {
            value: branchValue, editing: editingBranch, setEditing: setEditingBranch,
            inputProps: () => inputProps('branch', branchValue, setBranchValue, setEditingBranch),
        },
        pr: {
            value: prUrlValue, editing: editingPrUrl, setEditing: setEditingPrUrl,
            inputProps: () => inputProps('pr_url', prUrlValue, setPrUrlValue, setEditingPrUrl),
        },
        copiedField, copyToClipboard, error,
    };
}
