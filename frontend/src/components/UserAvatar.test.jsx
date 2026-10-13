import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { UserAvatar } from './UserAvatar';

describe('UserAvatar', () => {
    it('renders a default cartoon (no initial letter) when no picture is set', () => {
        const { container } = render(<UserAvatar profile={{ name: 'ali', avatar_url: '' }} />);
        expect(container.querySelector('svg')).toBeTruthy();
        expect(container.querySelector('img')).toBeNull();
    });

    it('is stable for the same name', () => {
        const a = render(<UserAvatar name="ali" />).container.innerHTML;
        const b = render(<UserAvatar name="ali" />).container.innerHTML;
        expect(a).toBe(b);
    });

    it('renders a chosen preset', () => {
        const { container } = render(<UserAvatar profile={{ name: 'ali', avatar_url: 'preset:3' }} />);
        expect(container.querySelector('svg')).toBeTruthy();
    });

    it('renders an uploaded image', () => {
        render(<UserAvatar profile={{ name: 'ali', avatar_url: 'data:image/jpeg;base64,AAAA' }} />);
        expect(screen.getByRole('img', { name: 'ali' }).getAttribute('src')).toBe('data:image/jpeg;base64,AAAA');
    });
});
