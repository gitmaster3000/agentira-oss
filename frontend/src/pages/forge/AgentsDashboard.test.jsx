import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { EmptyState } from './AgentsDashboard';

describe('AgentsDashboard EmptyState', () => {
    it('explains managed agents need a daemon and where bots live', () => {
        render(<EmptyState />);
        expect(screen.getByText('No managed agents yet')).toBeTruthy();
        expect(screen.getByText(/daemon is connected/)).toBeTruthy();
        expect(screen.getByText(/do not need a daemon and are listed in Settings/)).toBeTruthy();
        expect(screen.queryByText(/auto-synced/)).toBeNull();
    });
});
