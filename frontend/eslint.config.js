import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

// Rendering rules: docs-oss/docs/technical/frontend-performance.md
const RAW_NETWORK = [
    {
        selector: "CallExpression[callee.name='fetch']",
        message: 'Use api.request() (api.js) — it dedupes GETs and caches. No raw fetch in components.',
    },
    {
        selector: "CallExpression[callee.object.name='axios']",
        message: 'Use api.request() (api.js). axios is not allowed.',
    },
    {
        selector: "ImportDeclaration[source.value='axios']",
        message: 'Use api.request() (api.js). axios is not allowed.',
    },
];

// TODO(AP-698): existing offenders. Shrink this list as the audit splits each file; never add to it.
const MAX_LINES_ALLOW_LIST = [
    'src/pages/forge/AgentDetail.jsx',
    'src/pages/Settings.jsx',
    'src/pages/forge/RunDetail.jsx',
    'src/pages/Chat.jsx',
    'src/components/RoadmapView/RoadmapView.jsx',
    'src/pages/ProjectSettings.jsx',
    'src/components/TaskDetailModal.jsx',
    'src/pages/WorkflowEngine.jsx',
    'src/components/CreateProjectWizard.jsx',
    'src/pages/forge/ConductorPage.jsx',
    'src/pages/EpicPage.jsx',
    'src/components/FloatingChat.jsx',
    'src/pages/ProjectLayout.jsx',
];

// TODO(AP-698): existing exhaustive-deps violations. Fix the deps and remove the file; never add to it.
const EXHAUSTIVE_DEPS_ALLOW_LIST = [
    'src/components/TaskDetail/AttachmentPreview.jsx',
    'src/components/TaskDetail/AttachmentsSection.jsx',
    'src/components/TaskDetailModal.jsx',
    'src/pages/Backlog.jsx',
    'src/pages/CliAuth.jsx',
    'src/pages/GitHubCallback.jsx',
    'src/pages/Landing.jsx',
    'src/pages/Login.jsx',
    'src/pages/ProjectLayout.jsx',
    'src/pages/ProjectSettings.jsx',
    'src/pages/Settings.jsx',
    'src/pages/Signup.jsx',
    'src/pages/forge/AgentsDashboard.jsx',
    'src/pages/forge/RunDetail.jsx',
    'src/pages/forge/RunsDashboard.jsx',
    'src/pages/forge/RuntimesDashboard.jsx',
];

export default [
    { ignores: ['dist/**', 'node_modules/**', 'design/**'] },
    {
        files: ['**/*.{js,jsx}'],
        plugins: { 'react-hooks': reactHooks },
        languageOptions: {
            ecmaVersion: 'latest',
            sourceType: 'module',
            parserOptions: { ecmaFeatures: { jsx: true } },
            globals: { ...globals.browser, ...globals.node },
        },
        linterOptions: { reportUnusedDisableDirectives: 'off' },
        rules: {
            'react-hooks/rules-of-hooks': 'error',
            'react-hooks/exhaustive-deps': 'error',
            'no-restricted-syntax': ['error', ...RAW_NETWORK],
        },
    },
    {
        files: ['src/pages/**/*.{js,jsx}', 'src/components/**/*.{js,jsx}'],
        ignores: ['**/*.test.{js,jsx}'],
        rules: { 'max-lines': ['warn', { max: 400, skipBlankLines: true, skipComments: true }] },
    },
    { files: EXHAUSTIVE_DEPS_ALLOW_LIST, rules: { 'react-hooks/exhaustive-deps': 'off' } },
    { files: MAX_LINES_ALLOW_LIST, rules: { 'max-lines': 'off' } },
    { files: ['src/api.js', 'src/telemetry.js'], rules: { 'no-restricted-syntax': 'off' } },
];
