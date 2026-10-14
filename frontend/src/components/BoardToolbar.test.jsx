import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BoardToolbar } from './BoardToolbar';

const members = [
    { id: 'm1', name: 'alice', display_name: 'Alice' },
    { id: 'm2', name: 'bob', display_name: 'Bob' },
];
const epics = [{ id: 'e1', title: 'Board UX' }];

function setup(over = {}) {
    const props = {
        projectId: 'P1', members, epics,
        searchQuery: '', setSearchQuery: vi.fn(),
        filterPriority: '', setFilterPriority: vi.fn(),
        filterAssignee: '', setFilterAssignee: vi.fn(),
        filterEpic: '', setFilterEpic: vi.fn(),
        onCreate: vi.fn(),
        ...over,
    };
    render(<BoardToolbar {...props} />);
    return props;
}

describe('BoardToolbar', () => {
    beforeEach(() => localStorage.clear());

    it('search updates query and "/" focuses it', () => {
        const p = setup();
        const input = screen.getByLabelText('Search board');
        fireEvent.keyDown(document.body, { key: '/' });
        expect(document.activeElement).toBe(input);
        fireEvent.change(input, { target: { value: 'abc' } });
        expect(p.setSearchQuery).toHaveBeenCalledWith('abc');
    });

    it('avatar click toggles assignee filter', () => {
        const p = setup();
        fireEvent.click(screen.getByTitle('Alice'));
        expect(p.setFilterAssignee).toHaveBeenCalledWith('alice');
    });

    it('priority and epic selection set filters; badge counts active filters', () => {
        const p = setup({ filterPriority: 'high', filterAssignee: 'bob' });
        expect(screen.getByText('2')).toBeTruthy();
        fireEvent.click(screen.getByText('Filter'));
        fireEvent.click(screen.getByText('Critical'));
        expect(p.setFilterPriority).toHaveBeenCalledWith('critical');
        fireEvent.click(screen.getByText('Epic'));
        fireEvent.click(screen.getByText('Board UX'));
        expect(p.setFilterEpic).toHaveBeenCalledWith('e1');
    });

    it('Clear filters hidden when nothing active', () => {
        setup();
        expect(screen.queryByText('Clear filters')).toBeNull();
    });

    it('Clear filters button resets everything', () => {
        const p = setup({ filterPriority: 'low', filterEpic: 'e1' });
        fireEvent.click(screen.getByText('Clear filters'));
        expect(p.setSearchQuery).toHaveBeenCalledWith('');
        expect(p.setFilterPriority).toHaveBeenCalledWith('');
        expect(p.setFilterAssignee).toHaveBeenCalledWith('');
        expect(p.setFilterEpic).toHaveBeenCalledWith('');
    });

    it('New task calls onCreate', () => {
        const p = setup();
        fireEvent.click(screen.getByText('New task'));
        expect(p.onCreate).toHaveBeenCalled();
    });
});
