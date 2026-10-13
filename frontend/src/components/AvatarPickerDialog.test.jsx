import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { AvatarPickerDialog } from './AvatarPickerDialog';
import { PRESET_COUNT } from './UserAvatar';

describe('AvatarPickerDialog', () => {
    it('lists every character and reports the chosen preset', () => {
        const onSelect = vi.fn();
        render(<AvatarPickerDialog value="" onSelect={onSelect} onClose={() => {}} />);
        expect(screen.getAllByRole('button', { name: /^Character / })).toHaveLength(PRESET_COUNT);
        fireEvent.click(screen.getByRole('button', { name: 'Character 3' }));
        expect(onSelect).toHaveBeenCalledWith('preset:2');
    });

    it('offers "Use default" only when a picture is set, and resets with empty value', () => {
        const onSelect = vi.fn();
        const { rerender } = render(<AvatarPickerDialog value="" onSelect={onSelect} onClose={() => {}} />);
        expect(screen.queryByText('Use default')).toBeNull();
        rerender(<AvatarPickerDialog value="preset:1" onSelect={onSelect} onClose={() => {}} />);
        fireEvent.click(screen.getByText('Use default'));
        expect(onSelect).toHaveBeenCalledWith('');
    });

    it('closes on Escape', () => {
        const onClose = vi.fn();
        render(<AvatarPickerDialog value="" onSelect={() => {}} onClose={onClose} />);
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(onClose).toHaveBeenCalled();
    });
});
