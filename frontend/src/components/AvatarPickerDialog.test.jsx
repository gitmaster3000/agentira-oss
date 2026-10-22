import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { AvatarPickerDialog } from './AvatarPickerDialog';
import { PRESET_COUNT, BOT_PRESET_COUNT } from './UserAvatar';

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

    it('bot kind lists 16+ robots and reports bot:<n>', () => {
        const onSelect = vi.fn();
        render(<AvatarPickerDialog kind="bot" value="" onSelect={onSelect} onClose={() => {}} />);
        expect(screen.getByText('Pick a robot, or upload an image.')).toBeTruthy();
        expect(screen.queryAllByRole('button', { name: /^Character / })).toHaveLength(0);
        expect(screen.getAllByRole('button', { name: /^Robot / })).toHaveLength(BOT_PRESET_COUNT);
        expect(BOT_PRESET_COUNT).toBeGreaterThanOrEqual(16);
        fireEvent.click(screen.getByRole('button', { name: 'Robot 3' }));
        expect(onSelect).toHaveBeenCalledWith('bot:2');
        expect(screen.getByText('Upload a photo')).toBeTruthy();
    });
});
