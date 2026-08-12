// @ts-check
import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Agentira',
  tagline: 'Self-hosted orchestration for AI coding agents',
  favicon: 'img/favicon.ico',

  // Site is published from the docs repo; source lives in the monorepo.
  url: 'https://gitmaster3000.github.io',
  baseUrl: '/agentira-oss-docs/',

  organizationName: 'gitmaster3000',
  projectName: 'agentira-oss-docs',
  deploymentBranch: 'gh-pages',
  trailingSlash: false,

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          routeBasePath: '/',
          editUrl:
            'https://github.com/gitmaster3000/agentira-oss/tree/main/docs-oss/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        defaultMode: 'dark',
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'Agentira',
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'userGuide',
            position: 'left',
            label: 'User guide',
          },
          {
            type: 'docSidebar',
            sidebarId: 'technical',
            position: 'left',
            label: 'Technical',
          },
          {
            type: 'docSidebar',
            sidebarId: 'contributing',
            position: 'left',
            label: 'Contributing',
          },
          {
            href: 'https://github.com/gitmaster3000/agentira-oss',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Documentation',
            items: [
              {label: 'Install Agentira', to: '/user-guide/install'},
              {label: 'Architecture', to: '/technical/architecture'},
              {label: 'MCP tool reference', to: '/technical/mcp-tools'},
            ],
          },
          {
            title: 'Project',
            items: [
              {
                label: 'Source code',
                href: 'https://github.com/gitmaster3000/agentira-oss',
              },
              {
                label: 'Report an issue',
                href: 'https://github.com/gitmaster3000/agentira-oss/issues',
              },
              {
                label: 'Contribute',
                to: '/contributing/',
              },
            ],
          },
        ],
        copyright: `Agentira. Licensed under Apache-2.0.`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['bash', 'json', 'yaml', 'python', 'sql'],
      },
    }),
};

export default config;
