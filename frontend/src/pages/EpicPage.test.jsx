import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EpicPage } from './EpicPage';
import { api } from '../api';

vi.mock('react-router-dom', () => ({
    useParams: () => ({ epicId: 'e1' }),
    useNavigate: () => vi.fn(),
    Link: ({ children }) => children,
}));
vi.mock('../components/Breadcrumbs', () => ({ Breadcrumbs: () => null }));
vi.mock('../api', () => ({
    api: {
        getEpic: vi.fn(),
        getEpicTasks: vi.fn(),
        listEpicAttachments: vi.fn(),
        updateEpic: vi.fn(),
    },
}));

describe('EpicPage — sprint status (Loop v1)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.getEpic.mockResolvedValue({ id: 'e1', project_id: 'p1', title: 'Loop', status: 'backlog' });
        api.getEpicTasks.mockResolvedValue([]);
        api.listEpicAttachments.mockResolvedValue([]);
        api.updateEpic.mockImplementation(async (_id, body) => ({ id: 'e1', project_id: 'p1', title: 'Loop', ...body }));
    });

    it('puts the epic in the current sprint', async () => {
        render(<EpicPage />);
        const select = await screen.findByLabelText(/epic status/i);
        expect(select.value).toBe('backlog');
        fireEvent.change(select, { target: { value: 'in_progress' } });
        await waitFor(() => expect(api.updateEpic).toHaveBeenCalledWith('e1', { status: 'in_progress' }));
    });
});
