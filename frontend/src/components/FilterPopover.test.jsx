import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FilterPopover } from './FilterPopover';
import { emptyFilters, countFilterOptions } from '../lib/taskFilters';

const counts = countFilterOptions([
    { priority: 'high', assignee: 'ann', tags: ['bug'] },
    { priority: 'high', assignee: null, tags: [] },
]);

describe('FilterPopover', () => {
    it('shows no badge when nothing selected', () => {
        render(<FilterPopover filters={emptyFilters()} counts={counts} onChange={() => {}} />);
        expect(screen.queryByTestId('filter-badge')).toBeNull();
    });
    it('badge shows active count', () => {
        const filters = { ...emptyFilters(), priorities: new Set(['high']), labels: new Set(['bug']) };
        render(<FilterPopover filters={filters} counts={counts} onChange={() => {}} />);
        expect(screen.getByTestId('filter-badge').textContent).toBe('2');
    });
    it('renders three columns with counts and toggles a value', () => {
        const onChange = vi.fn();
        render(<FilterPopover filters={emptyFilters()} counts={counts} onChange={onChange} />);
        fireEvent.click(screen.getByText('Filter'));
        expect(screen.getByText('Unassigned')).toBeTruthy();
        fireEvent.click(screen.getByLabelText(/High/));
        expect([...onChange.mock.calls[0][0].priorities]).toEqual(['high']);
    });
});
