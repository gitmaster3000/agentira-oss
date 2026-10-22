import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { UserAvatar, BOT_PRESET_COUNT } from './UserAvatar';

describe('UserAvatar', () => {
    it('renders a default cartoon (no initial letter) when no picture is set', () => {
        const { container } = render(<UserAvatar profile={{ name: 'ali', avatar_url: '' }} />);
        expect(container.querySelector('svg')).toBeTruthy();
        expect(container.querySelector('img')).toBeNull();
    });

    it('is stable for the same name', () => {
        const a = render(<UserAvatar name="ali" />).container.innerHTML;
        const b = render(<UserAvatar name="ali" />).container.innerHTML;
        expect(a).toBe(b);
    });

    it('renders a chosen preset', () => {
        const { container } = render(<UserAvatar profile={{ name: 'ali', avatar_url: 'preset:3' }} />);
        expect(container.querySelector('svg')).toBeTruthy();
    });

    it('renders an uploaded image', () => {
        render(<UserAvatar profile={{ name: 'ali', avatar_url: 'data:image/jpeg;base64,AAAA' }} />);
        expect(screen.getByRole('img', { name: 'ali' }).getAttribute('src')).toBe('data:image/jpeg;base64,AAAA');
    });

    it('defaults bots and agents to a robot, people to a cartoon', () => {
        for (const account_type of ['external_agent', 'agentira_agent']) {
            const { container } = render(<UserAvatar profile={{ name: 'helper', account_type, avatar_url: '' }} />);
            expect(container.querySelector('svg[data-robot]')).toBeTruthy();
        }
        const person = render(<UserAvatar profile={{ name: 'helper', account_type: 'human', avatar_url: '' }} />).container;
        expect(person.querySelector('svg[data-robot]')).toBeNull();
    });

    it('gives the same bot the same robot', () => {
        const bot = { name: 'helper', account_type: 'external_agent', avatar_url: '' };
        expect(render(<UserAvatar profile={bot} />).container.innerHTML).toBe(render(<UserAvatar profile={bot} />).container.innerHTML);
    });

    it('renders a chosen bot: value and offers 16+ robots', () => {
        expect(BOT_PRESET_COUNT).toBeGreaterThanOrEqual(16);
        const { container } = render(<UserAvatar profile={{ name: 'x', avatar_url: 'bot:9' }} />);
        expect(container.querySelector('svg[data-robot]')).toBeTruthy();
    });

    it('keeps an uploaded image on a bot', () => {
        render(<UserAvatar profile={{ name: 'helper', account_type: 'external_agent', avatar_url: 'data:image/jpeg;base64,AAAA' }} />);
        expect(screen.getByRole('img', { name: 'helper' })).toBeTruthy();
    });
});
