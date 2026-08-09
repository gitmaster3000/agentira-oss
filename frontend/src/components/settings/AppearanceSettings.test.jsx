import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AppearanceSettings } from './AppearanceSettings';

beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
});

describe('AppearanceSettings', () => {
    it('offers Day and Night, with Night selected by default', () => {
        render(<AppearanceSettings />);
        expect(screen.getByText('Day')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Night/ }).getAttribute('aria-pressed')).toBe('true');
        expect(screen.getByRole('button', { name: /Day/ }).getAttribute('aria-pressed')).toBe('false');
    });

    it('switching to Day paints and persists the theme', () => {
        render(<AppearanceSettings />);
        fireEvent.click(screen.getByRole('button', { name: /Day/ }));

        expect(document.documentElement.dataset.theme).toBe('light');
        expect(localStorage.getItem('theme')).toBe('light');
        expect(screen.getByRole('button', { name: /Day/ }).getAttribute('aria-pressed')).toBe('true');
    });

    it('reflects the stored theme on mount', () => {
        localStorage.setItem('theme', 'light');
        render(<AppearanceSettings />);
        expect(screen.getByRole('button', { name: /Day/ }).getAttribute('aria-pressed')).toBe('true');
    });
});
