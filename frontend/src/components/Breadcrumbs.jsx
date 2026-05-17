/**
 * AP-109: canonical breadcrumb nav for detail pages.
 *
 * Two ways to use:
 *   1. <Breadcrumbs entity="run" data={run} /> — preferred. The hierarchy
 *      for each entity type is defined in BUILDERS below, so every detail
 *      page renders a consistent path without duplicating logic.
 *   2. <Breadcrumbs items={[...]} /> — escape hatch for one-off pages.
 *
 * Renders `A › B › C` where every item except the last is a link.
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

// One place that knows the hierarchy for every entity type. Adding a new
// detail page = adding one entry here, not editing the page itself.
//
// Each builder receives the loaded entity (or null while loading) and
// returns an array of crumb items: { label, to? } — last item has no `to`.
const BUILDERS = {
    run: (run, opts = {}) => {
        const fromGlobal = opts.from === 'runs';
        const useAgentPath = run?.agent_id && !fromGlobal;
        return [
            { label: 'Forge', to: '/forge/overview' },
            ...(useAgentPath ? [
                // Agent context: "Forge › Agents › <name> › Runs › Run <id>".
                // "Runs" sends you to *this agent's* Runs tab, not the global
                // list — that's the slice you were drilling into.
                { label: 'Agents', to: '/forge/agents' },
                { label: run.agent_name || `agent ${run.agent_id.slice(0, 8)}`,
                  to: `/forge/agents/${run.agent_id}` },
                { label: 'Runs', to: `/forge/agents/${run.agent_id}?tab=runs` },
            ] : [
                // Global context: came from /forge/runs or Forge overview,
                // or there's no agent. Back-link is the global runs list.
                { label: 'Runs', to: '/forge/runs' },
            ]),
            { label: run ? `Run ${run.id.slice(0, 8)}` : 'Run' },
        ];
    },

    agent: (agent) => [
        { label: 'Forge', to: '/forge/overview' },
        { label: 'Agents', to: '/forge/agents' },
        { label: agent?.name || 'Agent' },
    ],

    task: (task) => [
        { label: 'Studio', to: '/studio' },
        ...(task?.project_id ? [{
            label: task.project_name || 'Board',
            to: `/studio/project/${task.project_id}/board`,
        }] : []),
        { label: task?.key || task?.title || 'Task' },
    ],

    epic: (epic) => [
        { label: 'Studio', to: '/studio' },
        ...(epic?.project_id ? [{
            label: epic.project_name || 'Board',
            to: `/studio/project/${epic.project_id}/board`,
        }] : []),
        { label: epic?.title || 'Epic' },
    ],
};

export function Breadcrumbs({ entity, data, opts, items }) {
    let resolved = items;
    if (!resolved && entity) {
        const build = BUILDERS[entity];
        if (!build) {
            console.warn(`Breadcrumbs: no builder for entity "${entity}"`);
            return null;
        }
        resolved = build(data, opts);
    }
    if (!resolved || resolved.length === 0) return null;

    return (
        <nav className="flex items-center gap-1 text-sm text-text-tertiary min-w-0" aria-label="Breadcrumb">
            {resolved.map((item, i) => {
                const isLast = i === resolved.length - 1;
                return (
                    <React.Fragment key={i}>
                        {i > 0 && (
                            <ChevronRight className="w-3.5 h-3.5 text-text-tertiary/60 flex-shrink-0" />
                        )}
                        {isLast || !item.to ? (
                            <span className="text-text-secondary truncate" title={item.label}>
                                {item.label}
                            </span>
                        ) : (
                            <Link
                                to={item.to}
                                className="hover:text-text-primary transition-colors truncate"
                                title={item.label}
                            >
                                {item.label}
                            </Link>
                        )}
                    </React.Fragment>
                );
            })}
        </nav>
    );
}
