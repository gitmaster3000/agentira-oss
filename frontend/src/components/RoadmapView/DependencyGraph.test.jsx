import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { DependencyGraph } from './DependencyGraph';

vi.mock('@xyflow/react', () => ({
    MarkerType: { ArrowClosed: 'arrow-closed' },
    ReactFlow: ({ nodes, onNodeClick, children }) => (
        <div>
            {nodes.map(node => (
                <button key={node.id} type="button" onClick={() => onNodeClick({}, node)}>
                    {node.data.label}
                </button>
            ))}
            {children}
        </div>
    ),
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
}));

const EPICS = [{
    name: 'Launch',
    tasks: [
        { id: 't1', key: 'AP-41', title: 'Prepare data', status: 'done' },
        { id: 't2', key: 'AP-42', title: 'Ship feature', status: 'todo', is_blocked: true },
    ],
}];

function TaskDestination() {
    const { taskId } = useParams();
    return <div>Full task {taskId}</div>;
}

describe('DependencyGraph', () => {
    it('labels edge direction and opens nodes using short task keys', () => {
        render(
            <MemoryRouter initialEntries={['/studio/project/p1/roadmap']}>
                <Routes>
                    <Route
                        path="/studio/project/:projectId/roadmap"
                        element={(
                            <DependencyGraph
                                epics={EPICS}
                                dependencies={[{ id: 'd1', task_id: 't2', depends_on_id: 't1' }]}
                            />
                        )}
                    />
                    <Route path="/studio/tasks/:taskId" element={<TaskDestination />} />
                </Routes>
            </MemoryRouter>,
        );

        expect(screen.getByText(/blocker → dependent/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /AP-42 Ship feature/ }));
        expect(screen.getByText('Full task AP-42')).toBeInTheDocument();
    });
});
