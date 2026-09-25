import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DependencyGraph } from './DependencyGraph';

const mocks = vi.hoisted(() => ({ reactFlowProps: vi.fn() }));

vi.mock('@xyflow/react', () => ({
    MarkerType: { ArrowClosed: 'arrow-closed', Arrow: 'arrow' },
    ReactFlow: (props) => {
        mocks.reactFlowProps(props);
        return (
            <div>
                {props.nodes.map(node => (
                    <button key={node.id} type="button" onClick={() => props.onNodeClick({}, node)}>
                        {node.data.label}
                    </button>
                ))}
                {props.children}
            </div>
        );
    },
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

describe('DependencyGraph', () => {
    beforeEach(() => mocks.reactFlowProps.mockClear());

    it('labels edge direction, uses static edges, and opens nodes in the task side view', () => {
        const onOpenTask = vi.fn();
        render(
            <DependencyGraph
                epics={EPICS}
                dependencies={[{ id: 'd1', task_id: 't2', depends_on_id: 't1' }]}
                onOpenTask={onOpenTask}
            />,
        );

        expect(screen.getByText(/blocker → dependent/)).toBeInTheDocument();
        expect(mocks.reactFlowProps).toHaveBeenCalledWith(expect.objectContaining({
            edges: [expect.objectContaining({ id: 'd1', animated: false })],
        }));
        fireEvent.click(screen.getByRole('button', { name: /AP-42 Ship feature/ }));
        expect(onOpenTask).toHaveBeenCalledWith('AP-42');
    });

    it('draws child → parent links dashed, alongside blocking links', () => {
        const epics = [{
            name: 'Launch',
            tasks: [
                { id: 't1', key: 'AP-41', title: 'Parent', status: 'todo' },
                { id: 't2', key: 'AP-42', title: 'Child', status: 'todo', parent_id: 't1' },
            ],
        }];
        render(<DependencyGraph epics={epics} dependencies={[]} />);

        expect(mocks.reactFlowProps).toHaveBeenCalledWith(expect.objectContaining({
            edges: [expect.objectContaining({
                id: 'parent-t2', source: 't2', target: 't1',
                style: expect.objectContaining({ strokeDasharray: '4 3' }),
            })],
        }));
    });
});
