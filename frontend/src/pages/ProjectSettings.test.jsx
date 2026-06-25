import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ProjectSettings } from './ProjectSettings';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', () => ({
    useParams: () => ({ projectId: 'p1' }),
    useLocation: () => ({ hash: '' }),
    useNavigate: () => navigateSpy,
}));

vi.mock('../api', () => ({
    api: {
        getProject: vi.fn(),
        deleteProject: vi.fn(),
        listProjectRepos: vi.fn().mockResolvedValue([]),
    },
}));

import { api } from '../api';

describe('ProjectSettings — delete (danger zone)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'Doomed' });
        api.deleteProject.mockResolvedValue({ ok: true });
    });

    it('deletes via the confirm dialog, then navigates to the studio root', async () => {
        render(<ProjectSettings />);

        // Danger zone + delete trigger render on the General tab.
        const trigger = await screen.findByRole('button', { name: /delete project/i });
        fireEvent.click(trigger);

        // Confirm dialog appears with the cascade warning; nothing deleted yet.
        await screen.findByText(/permanently deletes the project/i);
        expect(api.deleteProject).not.toHaveBeenCalled();

        // Confirm → delete is called and we leave the page.
        fireEvent.click(screen.getByRole('button', { name: /delete permanently/i }));
        await waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith('p1'));
        expect(navigateSpy).toHaveBeenCalledWith('/studio');
    });

    it('cancelling the dialog deletes nothing', async () => {
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: /delete project/i }));
        fireEvent.click(await screen.findByRole('button', { name: /cancel/i }));
        await waitFor(() =>
            expect(screen.queryByText(/permanently deletes the project/i)).not.toBeInTheDocument());
        expect(api.deleteProject).not.toHaveBeenCalled();
        expect(navigateSpy).not.toHaveBeenCalled();
    });
});
