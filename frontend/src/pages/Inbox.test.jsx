import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { Inbox } from './Inbox';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        getNotifications: vi.fn(),
        markNotificationRead: vi.fn(),
    },
}));

const NOTIFS = [
    { id: 'n1', type: 'assigned', title: 'assigned: task A', link: '/tasks/t1', read: false, created_at: new Date().toISOString() },
    { id: 'n2', type: 'completed', title: 'completed: task B', link: '/tasks/t2', read: true, created_at: new Date().toISOString() },
];

function renderInbox() {
    return render(
        <MemoryRouter initialEntries={['/studio/inbox']}>
            <Routes>
                <Route path="/studio/inbox" element={<Inbox />} />
                <Route path="/studio/tasks/:taskId" element={<div>TASK DETAIL</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('Inbox page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getNotifications.mockResolvedValue(NOTIFS);
        api.markNotificationRead.mockResolvedValue({});
    });

    it('lists notifications with an unread count', async () => {
        renderInbox();
        expect(await screen.findByText('assigned: task A')).toBeInTheDocument();
        expect(screen.getByText('completed: task B')).toBeInTheDocument();
        // one unread → count badge "1" appears
        expect(screen.getAllByText('1').length).toBeGreaterThan(0);
    });

    it('unread filter hides read notifications', async () => {
        renderInbox();
        await screen.findByText('assigned: task A');
        fireEvent.click(screen.getByText(/^Unread/));
        expect(screen.getByText('assigned: task A')).toBeInTheDocument();
        expect(screen.queryByText('completed: task B')).not.toBeInTheDocument();
    });

    it('clicking an unread row marks it read and navigates to the mapped studio route', async () => {
        renderInbox();
        fireEvent.click(await screen.findByText('assigned: task A'));
        await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith('n1'));
        expect(await screen.findByText('TASK DETAIL')).toBeInTheDocument();
    });

    it('mark all read clears the unread state', async () => {
        renderInbox();
        await screen.findByText('assigned: task A');
        fireEvent.click(screen.getByText('Mark all read'));
        await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith('n1'));
    });
});
