import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusPill } from './StatusPill';
import { STATUS, statusOf, timeAgo } from './theme';

describe('StatusPill', () => {
    it('renders a written label for every status — never colour alone', () => {
        for (const [status, cfg] of Object.entries(STATUS)) {
            const { unmount } = render(<StatusPill status={status} />);
            expect(screen.getByRole('status')).toHaveTextContent(cfg.label);
            unmount();
        }
    });

    it('appends the build step detail', () => {
        render(<StatusPill status="building" detail="2/4" />);
        expect(screen.getByRole('status')).toHaveAccessibleName('Building · 2/4');
    });

    it('gives live its pulsing dot and stopped a dashed outline', () => {
        const { rerender } = render(<StatusPill status="live" />);
        expect(screen.getByTestId('pill-glyph-live')).toBeInTheDocument();

        rerender(<StatusPill status="stopped" />);
        expect(screen.getByRole('status')).toHaveStyle({ borderStyle: 'dashed' });
    });

    it('falls back to the "no preview" pill for an unknown status', () => {
        render(<StatusPill status="wat" />);
        expect(screen.getByRole('status')).toHaveTextContent('No preview');
    });
});

describe('statusOf', () => {
    it('maps a missing deployment to "none"', () => {
        expect(statusOf(null)).toBe('none');
        expect(statusOf({ status: 'bogus' })).toBe('none');
        expect(statusOf({ status: 'crashed' })).toBe('crashed');
    });
});

describe('timeAgo', () => {
    it('renders relative times and tolerates missing input', () => {
        expect(timeAgo(null)).toBe('');
        expect(timeAgo(new Date(Date.now() - 5_000).toISOString())).toBe('just now');
        expect(timeAgo(new Date(Date.now() - 5 * 60_000).toISOString())).toBe('5 min ago');
        expect(timeAgo(new Date(Date.now() - 3 * 3600_000).toISOString())).toBe('3h ago');
        expect(timeAgo(new Date(Date.now() - 2 * 86_400_000).toISOString())).toBe('2d ago');
    });
});
