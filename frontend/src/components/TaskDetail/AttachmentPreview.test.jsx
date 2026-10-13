import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AttachmentPreview, previewKind } from './AttachmentPreview';
import { api } from '../../api';

vi.mock('../../api', () => ({ api: { fetchAttachmentBlob: vi.fn() } }));

describe('previewKind', () => {
    it('maps previewable extensions and rejects the rest', () => {
        expect(previewKind('a.PNG')).toBe('image');
        expect(previewKind('plan.md')).toBe('markdown');
        expect(previewKind('r.pdf')).toBe('pdf');
        expect(previewKind('x.html')).toBeNull();
        expect(previewKind('x.zip')).toBeNull();
    });
});

describe('AttachmentPreview', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        URL.createObjectURL = vi.fn(() => 'blob:x');
        URL.revokeObjectURL = vi.fn();
    });

    it('renders an image from the fetched blob', async () => {
        api.fetchAttachmentBlob.mockResolvedValue(new Blob(['x']));
        render(<AttachmentPreview attachment={{ id: 'A', filename: 's.png' }} onClose={() => {}} onDownload={() => {}} />);
        expect(await screen.findByRole('img')).toHaveAttribute('src', 'blob:x');
        expect(URL.createObjectURL.mock.calls[0][0].type).toBe('image/png');
    });

    it('renders markdown as markdown, not raw html', async () => {
        api.fetchAttachmentBlob.mockResolvedValue(new Blob(['# Title\n\n<script>1</script>']));
        const { container } = render(<AttachmentPreview attachment={{ id: 'A', filename: 'p.md' }} onClose={() => {}} onDownload={() => {}} />);
        expect(await screen.findByRole('heading', { name: 'Title' })).toBeInTheDocument();
        expect(container.querySelector('script')).toBeNull();
    });

    it('shows error and closes on Escape', async () => {
        api.fetchAttachmentBlob.mockRejectedValue(new Error('Preview failed (404)'));
        const onClose = vi.fn();
        render(<AttachmentPreview attachment={{ id: 'A', filename: 'r.pdf' }} onClose={onClose} onDownload={() => {}} />);
        expect(await screen.findByText('Preview failed (404)')).toBeInTheDocument();
        fireEvent.keyDown(window, { key: 'Escape' });
        await waitFor(() => expect(onClose).toHaveBeenCalled());
    });
});
