import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { NotificationSettings } from './NotificationSettings';
import { api } from '../../api';

const PREFS = {
    'task.created': { in_app: true, email: false, push: false },
    'bug.created': { in_app: true, email: false, push: false },
    'epic.created': { in_app: true, email: false, push: false },
};

vi.mock('../../api', () => ({
    api: { getNotificationPrefs: vi.fn(), setNotificationPrefs: vi.fn() },
}));

describe('NotificationSettings', () => {
    it('shows the matrix and saves a toggle', async () => {
        api.getNotificationPrefs.mockResolvedValue(PREFS);
        api.setNotificationPrefs.mockResolvedValue({ ...PREFS, 'bug.created': { ...PREFS['bug.created'], email: true } });
        render(<NotificationSettings />);
        const box = await screen.findByLabelText('New bug — Email');
        expect(box.checked).toBe(false);
        fireEvent.click(box);
        await waitFor(() => expect(api.setNotificationPrefs).toHaveBeenCalledWith({ 'bug.created': { email: true } }));
        await waitFor(() => expect(screen.getByLabelText('New bug — Email').checked).toBe(true));
    });
});
