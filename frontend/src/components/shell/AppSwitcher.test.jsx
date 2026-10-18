import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AppSwitcher } from './AppSwitcher';

vi.mock('../../currentProject', () => ({ useCurrentProjectId: () => 'p42' }));

const APPS = [{ key: 'easeign', name: 'Easeign', description: 'Design & prototypes', url: 'http://localhost:4400' }];

describe('AppSwitcher', () => {
    it('renders nothing when no apps are configured', () => {
        const { container } = render(<AppSwitcher apps={[]} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('lists Agentira as current plus connected apps on first open, no fetch', () => {
        render(<AppSwitcher apps={APPS} />);
        expect(screen.queryByRole('menu')).toBeNull();
        fireEvent.click(screen.getByLabelText('Switch app'));
        const items = screen.getAllByRole('menuitem');
        expect(items).toHaveLength(2);
        expect(items[0]).toHaveAttribute('aria-current', 'true');
        expect(screen.getByText('Easeign')).toBeInTheDocument();
    });

    it('opens the chosen app via the handoff and closes the menu', () => {
        const onOpen = vi.fn();
        render(<AppSwitcher apps={APPS} onOpen={onOpen} />);
        fireEvent.click(screen.getByLabelText('Switch app'));
        fireEvent.click(screen.getByText('Easeign'));
        expect(onOpen).toHaveBeenCalledWith(APPS[0], { project: 'p42' });
        expect(screen.queryByRole('menu')).toBeNull();
    });

    it('closes on Escape', () => {
        render(<AppSwitcher apps={APPS} />);
        fireEvent.click(screen.getByLabelText('Switch app'));
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByRole('menu')).toBeNull();
    });
});
