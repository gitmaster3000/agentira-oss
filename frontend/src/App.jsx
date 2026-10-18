import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ProjectLayout } from './pages/ProjectLayout';
import { Board } from './pages/Board';
import { Backlog } from './pages/Backlog';
import { ProjectOverview } from './pages/ProjectOverview';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { ForcePasswordChange } from './components/ForcePasswordChange';
import { Home } from './pages/Home';
import { TaskPage } from './pages/TaskPage';
import { ForgeLayout } from './pages/forge/ForgeLayout';
// Lazy loaded for perf (AP-433): these are heavier surfaces; split them out of main bundle to speed initial load and reduce memory pressure on deploy/other flows.
// These pages use named exports (no `export default`) — lazy() resolves
// `.default`, so plain `import(...)` here left every one of them undefined
// (React error #306 on every Forge/Chat route). Map the named export in.
const Chat = lazy(() => import('./pages/Chat'));
const ForgeOverview = lazy(() => import('./pages/forge/ForgeOverview').then(m => ({ default: m.ForgeOverview })));
const AgentsDashboard = lazy(() => import('./pages/forge/AgentsDashboard').then(m => ({ default: m.AgentsDashboard })));
const RuntimesDashboard = lazy(() => import('./pages/forge/RuntimesDashboard').then(m => ({ default: m.RuntimesDashboard })));
const AgentDetail = lazy(() => import('./pages/forge/AgentDetail').then(m => ({ default: m.AgentDetail })));
const RunsDashboard = lazy(() => import('./pages/forge/RunsDashboard').then(m => ({ default: m.RunsDashboard })));
const RunDetail = lazy(() => import('./pages/forge/RunDetail').then(m => ({ default: m.RunDetail })));
const ConductorPage = lazy(() => import('./pages/forge/ConductorPage').then(m => ({ default: m.ConductorPage })));
const ForgeSettings = lazy(() => import('./pages/forge/ForgeSettings').then(m => ({ default: m.ForgeSettings })));
// Secondary surfaces: split out of the main bundle (named exports -> map to default).
const page = (load, name) => lazy(() => load().then(m => ({ default: m[name] })));
const ProjectSettings = page(() => import('./pages/ProjectSettings'), 'ProjectSettings');
const RoadmapView = page(() => import('./components/RoadmapView/RoadmapView'), 'RoadmapView');
const Signup = page(() => import('./pages/Signup'), 'Signup');
const ForgotPassword = page(() => import('./pages/ForgotPassword'), 'ForgotPassword');
const ResetPassword = page(() => import('./pages/ResetPassword'), 'ResetPassword');
const GitHubCallback = page(() => import('./pages/GitHubCallback'), 'GitHubCallback');
const CliAuth = page(() => import('./pages/CliAuth'), 'CliAuth');
const Settings = page(() => import('./pages/Settings'), 'Settings');
const EpicPage = page(() => import('./pages/EpicPage'), 'EpicPage');
const ProjectEpics = page(() => import('./pages/ProjectEpics'), 'ProjectEpics');
const Inbox = page(() => import('./pages/Inbox'), 'Inbox');
const MyWork = page(() => import('./pages/MyWork'), 'MyWork');
const Workflow = page(() => import('./pages/Workflow'), 'Workflow');
const Deploy = page(() => import('./pages/Deploy'), 'Deploy');
const DevGlow = page(() => import('./pages/DevGlow'), 'DevGlow');
import { ROUTES } from './routes';
import { PreviewBanner } from './components/PreviewBanner';

// Old "Welcome" stub replaced by Home — see pages/Home.jsx

function RequireAuth({ children }) {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    if (!user) return <Navigate to={ROUTES.WELCOME} replace />;
    // AP-306: force a password change before anything else if flagged.
    return <>{children}<ForcePasswordChange /></>;
}

function RedirectIfAuth({ children }) {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    if (user) return <Navigate to={ROUTES.STUDIO} replace />;
    return children;
}

function RootRedirect() {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    return user ? <Navigate to={ROUTES.STUDIO} replace /> : <Navigate to={ROUTES.WELCOME} replace />;
}

// /studio/board/:projectId → /studio/project/:projectId/board (PR #18 route rename)
function LegacyBoardRedirect() {
    const { projectId } = useParams();
    return <Navigate to={`/studio/project/${projectId}/board`} replace />;
}

export default function App() {
    return (
        <AuthProvider>
            <PreviewBanner />
            <BrowserRouter>
                <Suspense fallback={null}>
                <Routes>
                    {/* Public routes */}
                    <Route path={ROUTES.WELCOME} element={<RedirectIfAuth><Landing /></RedirectIfAuth>} />
                    <Route path={ROUTES.LOGIN} element={<RedirectIfAuth><Login /></RedirectIfAuth>} />
                    <Route path={ROUTES.SIGNUP} element={<RedirectIfAuth><Signup /></RedirectIfAuth>} />
                    <Route path={ROUTES.FORGOT_PASSWORD} element={<RedirectIfAuth><ForgotPassword /></RedirectIfAuth>} />
                    <Route path={ROUTES.RESET_PASSWORD} element={<ResetPassword />} />
                    <Route path={ROUTES.GITHUB_CALLBACK} element={<GitHubCallback />} />
                    <Route path="/cli-auth" element={<CliAuth />} />

                    {/* Studio routes (authenticated) */}
                    <Route path={ROUTES.STUDIO} element={<RequireAuth><Layout /></RequireAuth>}>
                        <Route index element={<Home />} />
                        <Route path="inbox" element={<Inbox />} />
                        <Route path="my-work" element={<MyWork />} />
                        <Route path="project/:projectId" element={<ProjectLayout />}>
                            <Route index element={<Navigate to="overview" replace />} />
                            <Route path="overview" element={<ProjectOverview />} />
                            <Route path="board" element={<Board />} />
                            <Route path="backlog" element={<Backlog />} />
                            <Route path="roadmap" element={<RoadmapView />} />
                            <Route path="calendar" element={<RoadmapView calendarOnly />} />
                            <Route path="epics" element={<ProjectEpics />} />
                            <Route path="workflow" element={<Workflow />} />
                            <Route path="deploy" element={<Deploy />} />
                            <Route path="settings" element={<ProjectSettings />} />
                        </Route>
                        {/* Legacy flat board route — redirect to the new nested form. */}
                        <Route path="board/:projectId" element={<LegacyBoardRedirect />} />
                        <Route path="settings" element={<Settings />} />
                        <Route path="tasks/:taskId" element={<TaskPage />} />
                        <Route path="epics/:epicId" element={<EpicPage />} />
                    </Route>

                    {/* Global Chat page (design §2.4) — in-shell, GET /forge/chats */}
                    <Route path={ROUTES.CHAT} element={<RequireAuth><Layout /></RequireAuth>}>
                        <Route index element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading chat…</div>}><Chat /></Suspense>} />
                    </Route>

                    {/* Root redirect */}
                    <Route path="/" element={<RootRedirect />} />

                    {/* Legacy redirects */}
                    <Route path="/board/:projectId" element={<Navigate to={ROUTES.STUDIO_PROJECT(':projectId')} replace />} />
                    <Route path="board/:projectId" element={<Navigate to={ROUTES.STUDIO_PROJECT(':projectId')} replace />} />
                    <Route path="/settings" element={<Navigate to={ROUTES.STUDIO_SETTINGS} replace />} />

                    {/* Forge routes */}
                    <Route path="/forge" element={<RequireAuth><ForgeLayout /></RequireAuth>}>
                        <Route index element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading…</div>}><ForgeOverview /></Suspense>} />
                        <Route path="agents" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading agents…</div>}><AgentsDashboard /></Suspense>} />
                        <Route path="agents/:agentId" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading agent…</div>}><AgentDetail /></Suspense>} />
                        <Route path="conductor" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading…</div>}><ConductorPage /></Suspense>} />
                        <Route path="runtimes" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading…</div>}><RuntimesDashboard /></Suspense>} />
                        <Route path="runs" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading runs…</div>}><RunsDashboard /></Suspense>} />
                        <Route path="runs/:runId" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading run…</div>}><RunDetail /></Suspense>} />
                        <Route path="settings" element={<Suspense fallback={<div style={{padding:16, textAlign:'center', color:'var(--text-secondary)'}}>Loading…</div>}><ForgeSettings /></Suspense>} />
                    </Route>

                    {/* Phase-0 token smoke (dev only — not linked from chrome) */}
                    <Route path="/dev/glow" element={<DevGlow />} />

                    {/* Catch-all */}
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
                </Suspense>
            </BrowserRouter>
        </AuthProvider>
    );
}
