import { describe, it, expect, beforeEach } from 'vitest';
import { THEMES, getTheme, setTheme, applyStoredTheme, subscribeTheme } from './theme';

beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
});

describe('theme', () => {
    it('defaults to dark when nothing is stored', () => {
        expect(getTheme()).toBe('dark');
    });

    it('returns the stored theme', () => {
        localStorage.setItem('theme', 'light');
        expect(getTheme()).toBe('light');
    });

    it('falls back to dark for an unknown stored value', () => {
        localStorage.setItem('theme', 'banana');
        expect(getTheme()).toBe('dark');
    });

    it('setTheme persists and paints the document', () => {
        setTheme('light');
        expect(localStorage.getItem('theme')).toBe('light');
        expect(document.documentElement.dataset.theme).toBe('light');

        setTheme('dark');
        expect(localStorage.getItem('theme')).toBe('dark');
        expect(document.documentElement.dataset.theme).toBe('dark');
    });

    it('ignores an unknown theme', () => {
        setTheme('light');
        setTheme('banana');
        expect(getTheme()).toBe('light');
    });

    it('applyStoredTheme paints the stored theme', () => {
        localStorage.setItem('theme', 'light');
        applyStoredTheme();
        expect(document.documentElement.dataset.theme).toBe('light');
    });

    it('notifies subscribers on change and stops after unsubscribe', () => {
        const seen = [];
        const off = subscribeTheme(t => seen.push(t));
        setTheme('light');
        off();
        setTheme('dark');
        expect(seen).toEqual(['light']);
    });

    it('exposes both themes', () => {
        expect(THEMES.map(t => t.id)).toEqual(['dark', 'light']);
    });
});
