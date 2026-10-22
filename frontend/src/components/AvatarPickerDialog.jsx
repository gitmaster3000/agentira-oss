import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { CartoonFace, RobotFace, PRESET_COUNT, BOT_PRESET_COUNT, presetValue, botPresetValue, resizeImageToDataUrl } from './UserAvatar';

// Modal for choosing a profile picture: a character or an uploaded image.
// kind='bot' offers robots instead. Calls onSelect(value) with 'preset:<n>' / 'bot:<n>', a data URL, or '' (use default).
export function AvatarPickerDialog({ value, onSelect, onClose, kind = 'person' }) {
    const [error, setError] = useState('');
    const isBot = kind === 'bot';
    const count = isBot ? BOT_PRESET_COUNT : PRESET_COUNT;
    const valueOf = isBot ? botPresetValue : presetValue;
    const Face = isBot ? RobotFace : CartoonFace;
    const noun = isBot ? 'Robot' : 'Character';
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [onClose]);

    async function onFile(e) {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        try { onSelect(await resizeImageToDataUrl(file)); }
        catch (err) { setError(err.message); }
    }

    return createPortal(
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
            <div role="dialog" aria-modal="true" aria-label="Choose a picture"
                className="relative bg-bg-card border border-border-subtle rounded-lg shadow-elevation-3 w-full max-w-md overflow-hidden animate-fade-in">
                <div className="p-6">
                    <h2 className="text-title-lg font-medium text-text-primary mb-1">Choose a picture</h2>
                    <p className="text-body-md text-text-secondary mb-4">{isBot ? 'Pick a robot, or upload an image.' : 'Pick a character, or upload your own photo.'}</p>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10 }}>
                        {Array.from({ length: count }, (_, i) => (
                            <button key={i} type="button" aria-label={`${noun} ${i + 1}`} aria-pressed={value === valueOf(i)}
                                onClick={() => onSelect(valueOf(i))}
                                style={{ padding: 0, borderRadius: '50%', overflow: 'hidden', cursor: 'pointer', lineHeight: 0, justifySelf: 'center',
                                    border: value === valueOf(i) ? '2px solid var(--accent-primary)' : '2px solid transparent' }}>
                                <Face index={i} size={48} />
                            </button>
                        ))}
                    </div>
                    {error && <div style={{ marginTop: 12, fontSize: 12, color: '#f87171' }}>{error}</div>}
                </div>
                <div className="px-6 py-4 border-t flex items-center justify-between gap-3" style={{ backgroundColor: 'var(--bg-panel)' }}>
                    <div className="flex gap-3">
                        <label className="btn btn-ghost" style={{ cursor: 'pointer' }}>
                            Upload a photo
                            <input type="file" accept="image/*" data-testid="avatar-upload" style={{ display: 'none' }} onChange={onFile} />
                        </label>
                        {value && <button type="button" className="btn btn-ghost" onClick={() => onSelect('')}>Use default</button>}
                    </div>
                    <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
                </div>
            </div>
        </div>,
        document.body
    );
}
