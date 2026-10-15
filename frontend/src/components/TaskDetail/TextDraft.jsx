import React, { useState } from 'react';

/**
 * Title / description text fields for edit mode. Each owns its draft, so a
 * keystroke re-renders only the field. The parent never holds the text in
 * state: `onDraft(text)` just records it (a ref write), and Save reads it.
 */
export function TitleEditor({ initial, onDraft, ...props }) {
    const [value, setValue] = useState(initial || '');
    return (
        <input
            {...props}
            value={value}
            onChange={e => { setValue(e.target.value); onDraft(e.target.value); }}
        />
    );
}

export function DescriptionEditor({ initial, onDraft, ...props }) {
    const [value, setValue] = useState(initial || '');
    return (
        <textarea
            {...props}
            value={value}
            onChange={e => { setValue(e.target.value); onDraft(e.target.value); }}
        />
    );
}
