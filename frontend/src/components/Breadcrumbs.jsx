/**
 * AP-109: canonical breadcrumb nav for detail pages.
 *
 * Two ways to use:
 *   1. <Breadcrumbs entity="run" data={run} /> — preferred. The hierarchy
 *      for each entity type is defined in BUILDERS below, so every detail
 *      page renders a consistent path without duplicating logic.
 *   2. <Breadcrumbs items={[...]} /> — escape hatch for one-off pages.
 *
 * Renders nothing in place: it publishes the path to the top bar (see
 * shell/crumbs.js, AppTopbar), where `A › B › C` shows next to Work | Build.
 */
import { useEffect } from 'react';
import { setCrumbs } from './shell/crumbs';

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
            { label: 'Build', to: '/forge/overview' },
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
        { label: 'Build', to: '/forge/overview' },
        { label: 'Agents', to: '/forge/agents' },
        { label: agent?.name || 'Agent' },
    ],

    task: (task) => [
        { label: 'Work', to: '/studio' },
        ...(task?.project_id ? [{
            label: task.project_name || 'Board',
            to: `/studio/project/${task.project_id}/board`,
        }] : []),
        { label: task?.key || task?.title || 'Task' },
    ],

    epic: (epic) => [
        { label: 'Work', to: '/studio' },
        ...(epic?.project_id ? [{
            label: epic.project_name || 'Board',
            to: `/studio/project/${epic.project_id}/board`,
        }] : []),
        { label: epic?.title || 'Epic' },
    ],
};

export function Breadcrumbs({ entity, data, opts, items }) {
    const build = BUILDERS[entity];
    if (!items && entity && !build) console.warn(`Breadcrumbs: no builder for entity "${entity}"`);
    const resolved = items || (build ? build(data, opts) : []);
    const key = JSON.stringify(resolved);
    useEffect(() => {
        setCrumbs(JSON.parse(key));
        return () => setCrumbs([]);
    }, [key]);
    return null;
}
