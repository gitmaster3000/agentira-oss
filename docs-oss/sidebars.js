/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  userGuide: [
    'intro',
    {
      type: 'category',
      label: 'Getting started',
      collapsed: false,
      items: [
        'user-guide/install',
        'user-guide/daemon',
        'user-guide/first-project',
      ],
    },
    {
      type: 'category',
      label: 'Working with projects',
      collapsed: false,
      items: [
        'user-guide/projects',
        'user-guide/tasks-and-board',
        'user-guide/attachments',
        'user-guide/members-and-roles',
      ],
    },
    {
      type: 'category',
      label: 'Working with agents',
      collapsed: false,
      items: [
        'user-guide/agents',
        'user-guide/running-agents',
        'user-guide/runs-and-artifacts',
        'user-guide/steering',
        'user-guide/conductor',
      ],
    },
    {
      type: 'category',
      label: 'Controls and safety',
      collapsed: false,
      items: [
        'user-guide/gates',
        'user-guide/sandbox-modes',
        'user-guide/notifications',
      ],
    },
    'user-guide/troubleshooting',
    'user-guide/glossary',
  ],

  technical: [
    'technical/architecture',
    'technical/concepts',
    'technical/run-lifecycle',
    'technical/run-state-machine',
    'technical/runtimes',
    {
      type: 'category',
      label: 'Interfaces',
      collapsed: false,
      items: [
        'technical/mcp-server',
        'technical/mcp-tools',
        'technical/rest-api',
      ],
    },
    {
      type: 'category',
      label: 'Subsystems',
      collapsed: false,
      items: [
        'technical/data-model',
        'technical/gates-and-evidence',
        'technical/sandbox',
      ],
    },
    {
      type: 'category',
      label: 'Operations',
      collapsed: false,
      items: [
        'technical/self-hosting',
        'technical/deployment',
        'technical/configuration',
      ],
    },
  ],

  contributing: [
    'contributing/index',
    'contributing/development-setup',
    'contributing/code-conventions',
    'contributing/adding-a-feature',
    'contributing/testing',
    'contributing/pull-requests',
    'contributing/documentation-style',
  ],
};

export default sidebars;
