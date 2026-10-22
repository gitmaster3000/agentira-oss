import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({}) }));
vi.mock('../api', () => ({ api: { updateProfile: vi.fn().mockResolvedValue({}) } }));

import { api } from '../api';
import { ProfileDetailsModal } from './Settings';

const bot = { id: 'b1', name: 'helper', display_name: 'Helper', account_type: 'external_agent', avatar_url: '', roles: [] };
const open = (profile, editable = true, onSaved = vi.fn()) =>
    render(<ProfileDetailsModal profile={profile} editable={editable} onClose={() => {}} onSaved={onSaved} />);

describe('ProfileDetailsModal bot picture', () => {
    it('shows a robot by default and saves the chosen robot', async () => {
        const onSaved = vi.fn();
        const { container } = open(bot, true, onSaved);
        expect(container.querySelector('svg[data-robot]')).toBeTruthy();
        expect(screen.getByText('Save').disabled).toBe(true);
        fireEvent.click(screen.getByText('Change picture'));
        fireEvent.click(screen.getByRole('button', { name: 'Robot 4' }));
        expect(screen.getByText('Save').disabled).toBe(false);
        fireEvent.click(screen.getByText('Save'));
        await waitFor(() => expect(api.updateProfile).toHaveBeenCalledWith('b1', { avatar_url: 'bot:3' }));
        await waitFor(() => expect(onSaved).toHaveBeenCalled());
    });

    it('hides Change picture for non-admins and for people', () => {
        open(bot, false);
        expect(screen.queryByText('Change picture')).toBeNull();
    });
});
