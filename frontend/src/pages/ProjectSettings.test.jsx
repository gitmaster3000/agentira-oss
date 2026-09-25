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
        updateProject: vi.fn(),
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

describe('ProjectSettings — clearing fields', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({
            id: 'p1', name: 'P', repo_path: '/old/path',
            repo_url: 'https://github.com/o/r', conventions_md: '# c',
        });
        api.updateProject.mockImplementation(async (_id, body) => ({ id: 'p1', name: 'P', ...body }));
    });

    it('sends "" (clear) not null (no change) for emptied text fields', async () => {
        render(<ProjectSettings />);
        const path = await screen.findByDisplayValue('/old/path');
        fireEvent.change(path, { target: { value: '' } });
        fireEvent.change(screen.getByDisplayValue('https://github.com/o/r'), { target: { value: '' } });
        fireEvent.change(screen.getByDisplayValue('# c'), { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        const body = api.updateProject.mock.calls[0][1];
        expect(body.repo_path).toBe('');
        expect(body.repo_url).toBe('');
        expect(body.conventions_md).toBe('');
    });
});

describe('ProjectSettings — verify command (Loop v1)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'P', verify_cmd: '', verify_timeout_minutes: 30 });
        api.updateProject.mockImplementation(async (_id, body) => ({ id: 'p1', name: 'P', ...body }));
    });

    it('saves the command that proves the project works', async () => {
        render(<ProjectSettings />);
        const field = await screen.findByLabelText(/command that proves the project works/i);
        fireEvent.change(field, { target: { value: 'scripts/verify.sh' } });
        fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        expect(api.updateProject.mock.calls[0][1].verify_cmd).toBe('scripts/verify.sh');
    });
});

describe('ProjectSettings — goals & direction (Loop v1)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'P', direction_md: 'old' });
        api.updateProject.mockImplementation(async (_id, body) => ({ id: 'p1', name: 'P', ...body }));
    });

    it('saves the direction the Conductor plans from', async () => {
        render(<ProjectSettings />);
        const field = await screen.findByLabelText(/goals & direction/i);
        expect(field.value).toBe('old');
        fireEvent.change(field, { target: { value: 'Ship Loop v1 first' } });
        fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        expect(api.updateProject.mock.calls[0][1].direction_md).toBe('Ship Loop v1 first');
    });
});
