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
        addProjectRepo: vi.fn(),
        listProjectAttachments: vi.fn().mockResolvedValue([{ id: 'f1', filename: 'brief.pdf', size_bytes: 10 }]),
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

        fireEvent.click(await screen.findByRole('button', { name: 'Danger zone' }));
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
        fireEvent.click(await screen.findByRole('button', { name: 'Danger zone' }));
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

    it('sends "" (clear) not null (no change) for an emptied text field', async () => {
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: 'Overview' }));
        fireEvent.change(await screen.findByDisplayValue('# c'), { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        const body = api.updateProject.mock.calls[0][1];
        expect(body.conventions_md).toBe('');
        // Legacy single-repo fields are no longer editable here; they round-trip untouched.
        expect(body.repo_path).toBe('/old/path');
        expect(body.repo_url).toBe('https://github.com/o/r');
    });

    it('offers to convert a legacy single repo into a real repo', async () => {
        api.addProjectRepo.mockResolvedValue({});
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: 'Repositories' }));
        fireEvent.click(await screen.findByRole('button', { name: /convert to a repo/i }));
        await waitFor(() => expect(api.addProjectRepo).toHaveBeenCalledWith('p1', expect.objectContaining({
            repo_url: 'https://github.com/o/r', repo_path: '/old/path', is_primary: true,
        })));
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
        fireEvent.click(await screen.findByRole('button', { name: 'Checks & workflow' }));
        const field = await screen.findByLabelText(/command that proves the project works/i);
        fireEvent.change(field, { target: { value: 'scripts/verify.sh' } });
        fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
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
        fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        expect(api.updateProject.mock.calls[0][1].direction_md).toBe('Ship Loop v1 first');
    });
});

describe('ProjectSettings — one save across sections', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'P', gates_enabled: false, sandbox_mode: '' });
        api.updateProject.mockImplementation(async (_id, body) => ({ id: 'p1', name: 'P', ...body }));
    });

    it('saves changes made in different sections together', async () => {
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: 'Checks & workflow' }));
        fireEvent.click(screen.getByRole('switch', { name: /require evidence/i }));
        fireEvent.click(await screen.findByRole('button', { name: 'Safety & isolation' }));
        fireEvent.click(screen.getByLabelText(/locked to the project folder/i));
        fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        const body = api.updateProject.mock.calls[0][1];
        expect(body.gates_enabled).toBe(true);
        expect(body.sandbox_mode).toBe('strict');
    });
});

describe('ProjectSettings — attach repo from a pasted address', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'P' });
        api.addProjectRepo.mockResolvedValue({});
        global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
            default_branch: 'trunk', language: 'Go', description: 'A thing', private: false }) });
    });

    it('fills name, branch and language from the address, keeps typed edits', async () => {
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: 'Repositories' }));
        fireEvent.click(await screen.findByRole('button', { name: /attach a repo/i }));
        fireEvent.change(screen.getByLabelText('Git address'), { target: { value: 'https://github.com/acme/web-app.git' } });
        expect(screen.getByLabelText('Name').value).toBe('web-app');
        await screen.findByText('Go');
        fireEvent.click(screen.getAllByRole('button', { name: 'Advanced' })[0]);
        expect(screen.getByLabelText('Main branch').value).toBe('trunk');

        fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'site' } });
        fireEvent.change(screen.getByLabelText('Git address'), { target: { value: 'https://github.com/acme/other.git' } });
        expect(screen.getByLabelText('Name').value).toBe('site');

        fireEvent.click(screen.getByRole('button', { name: /^attach repo$/i }));
        await waitFor(() => expect(api.addProjectRepo).toHaveBeenCalledWith('p1', expect.objectContaining({
            name: 'site', repo_url: 'https://github.com/acme/other.git', default_branch: 'trunk' })));
    });
});

describe('ProjectSettings — automation workflow switch', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'P', workflow_enabled: true });
        api.updateProject.mockImplementation(async (_id, body) => ({ id: 'p1', name: 'P', ...body }));
    });

    it('turning automation off saves workflow_enabled=false', async () => {
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: 'Checks & workflow' }));
        const box = await screen.findByRole('switch', { name: /run automation workflow/i });
        expect(box).toHaveAttribute('aria-checked', 'true');
        fireEvent.click(box);
        fireEvent.click(screen.getByRole('button', { name: /^save changes$/i }));
        await waitFor(() => expect(api.updateProject).toHaveBeenCalled());
        expect(api.updateProject.mock.calls[0][1].workflow_enabled).toBe(false);
    });
});


describe('ProjectSettings — attachments section', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getProject.mockResolvedValue({ id: 'p1', name: 'P', description: '' });
    });

    it('fetches attachments only when the Attachments section is opened', async () => {
        render(<ProjectSettings />);
        fireEvent.click(await screen.findByRole('button', { name: 'Repositories' }));
        expect(api.listProjectAttachments).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Attachments' }));
        expect(await screen.findByText('brief.pdf')).toBeInTheDocument();
        expect(api.listProjectAttachments).toHaveBeenCalledTimes(1);
    });
});
