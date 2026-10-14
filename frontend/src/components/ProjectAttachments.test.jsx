import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ProjectAttachments } from './ProjectAttachments';
import { api } from '../api';

vi.mock('../api', () => ({
    api: {
        listProjectAttachments: vi.fn(),
        uploadProjectAttachment: vi.fn(),
        deleteAttachment: vi.fn(),
        downloadAttachment: vi.fn(),
    },
}));

describe('ProjectAttachments', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        api.listProjectAttachments.mockResolvedValue([{ id: 'f1', filename: 'brief.pdf', size_bytes: 2048 }]);
    });

    it('loads and lists attachments on mount (one request)', async () => {
        render(<ProjectAttachments projectId="P1" />);
        expect(await screen.findByText('brief.pdf')).toBeInTheDocument();
        expect(screen.getByText('2.0 KB')).toBeInTheDocument();
        expect(api.listProjectAttachments).toHaveBeenCalledTimes(1);
        expect(api.listProjectAttachments).toHaveBeenCalledWith('P1');
    });
});
