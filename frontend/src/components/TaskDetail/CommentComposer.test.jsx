import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CommentComposer } from './CommentComposer';
import { TitleEditor, DescriptionEditor } from './TextDraft';

vi.mock('../../api', () => ({ api: { getProjectMembers: vi.fn(() => Promise.resolve([])) } }));

const MEMBERS = [{ id: 'u1', name: 'alice' }];
const type = (el, value) => fireEvent.change(el, { target: { value } });

describe('CommentComposer', () => {
    it.each(['page', 'panel'])('keeps typing local and submits once (%s)', async (variant) => {
        const onSubmit = vi.fn(() => Promise.resolve());
        render(<CommentComposer variant={variant} user={{ display_name: 'Ali' }} members={MEMBERS} onSubmit={onSubmit} />);
        const box = screen.getByRole('textbox');
        type(box, 'h'); type(box, 'he'); type(box, 'hey');
        expect(onSubmit).not.toHaveBeenCalled();
        fireEvent.submit(box.closest('form'));
        await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('hey'));
        await waitFor(() => expect(box.value).toBe(''));
    });

    it('does not submit an empty comment', () => {
        const onSubmit = vi.fn();
        render(<CommentComposer members={MEMBERS} onSubmit={onSubmit} />);
        type(screen.getByRole('textbox'), '   ');
        fireEvent.submit(screen.getByRole('textbox').closest('form'));
        expect(onSubmit).not.toHaveBeenCalled();
    });

    it('keeps the draft and alerts when posting fails', async () => {
        const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
        const onSubmit = vi.fn(() => Promise.reject(new Error('nope')));
        render(<CommentComposer members={MEMBERS} onSubmit={onSubmit} />);
        const box = screen.getByRole('textbox');
        type(box, 'keep me');
        fireEvent.submit(box.closest('form'));
        await waitFor(() => expect(alertSpy).toHaveBeenCalledWith('nope'));
        expect(box.value).toBe('keep me');
        alertSpy.mockRestore();
    });

    it('does not fetch members when the caller passes them', async () => {
        const { api } = await import('../../api');
        api.getProjectMembers.mockClear();
        render(<CommentComposer projectId="P1" members={MEMBERS} onSubmit={() => {}} />);
        expect(api.getProjectMembers).not.toHaveBeenCalled();
    });

    it('re-renders only itself while typing (parent render count stays flat)', () => {
        let parentRenders = 0;
        function Parent() {
            parentRenders += 1;
            return <CommentComposer members={MEMBERS} onSubmit={() => {}} />;
        }
        render(<Parent />);
        const before = parentRenders;
        const box = screen.getByRole('textbox');
        for (let i = 1; i <= 20; i++) type(box, 'x'.repeat(i));
        expect(parentRenders).toBe(before);
    });
});

describe('TitleEditor / DescriptionEditor', () => {
    it('own their draft and report it without re-rendering the parent', () => {
        let parentRenders = 0;
        const onTitle = vi.fn();
        const onDesc = vi.fn();
        function Parent() {
            parentRenders += 1;
            return (
                <>
                    <TitleEditor aria-label="Title" initial="Old" onDraft={onTitle} />
                    <DescriptionEditor aria-label="Description" initial="Body" onDraft={onDesc} />
                </>
            );
        }
        render(<Parent />);
        expect(screen.getByLabelText('Title').value).toBe('Old');
        expect(screen.getByLabelText('Description').value).toBe('Body');
        const before = parentRenders;
        type(screen.getByLabelText('Title'), 'New');
        type(screen.getByLabelText('Description'), 'Newer body');
        expect(screen.getByLabelText('Title').value).toBe('New');
        expect(onTitle).toHaveBeenLastCalledWith('New');
        expect(onDesc).toHaveBeenLastCalledWith('Newer body');
        expect(parentRenders).toBe(before);
    });
});
