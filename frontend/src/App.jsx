import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ProjectLayout } from './pages/ProjectLayout';
import { Board } from './pages/Board';
import { Backlog } from './pages/Backlog';
import { ProjectOverview } from './pages/ProjectOverview';
import { ProjectSettings } from './pages/ProjectSettings';
import { RoadmapView } from './components/RoadmapView/RoadmapView';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { Signup } from './pages/Signup';
import { ForgotPassword } from './pages/ForgotPassword';
import { ResetPassword } from './pages/ResetPassword';
import { ForcePasswordChange } from './components/ForcePasswordChange';
import { GitHubCallback } from './pages/GitHubCallback';
import { CliAuth } from './pages/CliAuth';
import { Settings } from './pages/Settings';
import { StudioDashboard } from './pages/StudioDashboard';
import { TaskPage } from './pages/TaskPage';
import { Chat } from './pages/Chat';
import { EpicPage } from './pages/EpicPage';
import { DevGlow } from './pages/DevGlow';
import { ForgeLayout } from './pages/forge/ForgeLayout';
import { ForgeOverview } from './pages/forge/ForgeOverview';
import { AgentsDashboard } from './pages/forge/AgentsDashboard';
import { RuntimesDashboard } from './pages/forge/RuntimesDashboard';
import { AgentDetail } from './pages/forge/AgentDetail';
import { RunsDashboard } from './pages/forge/RunsDashboard';
import { RunDetail } from './pages/forge/RunDetail';
import { ConductorPage } from './pages/forge/ConductorPage';
import { ForgeSettings } from './pages/forge/ForgeSettings';
import { ROUTES } from './routes';
import { PreviewBanner } from './components/PreviewBanner';

// Old "Welcome" stub replaced by StudioDashboard — see pages/StudioDashboard.jsx

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
                        <Route index element={<StudioDashboard />} />
                        <Route path="project/:projectId" element={<ProjectLayout />}>
                            <Route index element={<Navigate to="overview" replace />} />
                            <Route path="overview" element={<ProjectOverview />} />
                            <Route path="board" element={<Board />} />
                            <Route path="backlog" element={<Backlog />} />
                            <Route path="roadmap" element={<RoadmapView />} />
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
                        <Route index element={<Chat />} />
                    </Route>

                    {/* Root redirect */}
                    <Route path="/" element={<RootRedirect />} />

                    {/* Legacy redirects */}
                    <Route path="/board/:projectId" element={<Navigate to={ROUTES.STUDIO_PROJECT(':projectId')} replace />} />
                    <Route path="board/:projectId" element={<Navigate to={ROUTES.STUDIO_PROJECT(':projectId')} replace />} />
                    <Route path="/settings" element={<Navigate to={ROUTES.STUDIO_SETTINGS} replace />} />

                    {/* Forge routes */}
                    <Route path="/forge" element={<RequireAuth><ForgeLayout /></RequireAuth>}>
                        <Route index element={<ForgeOverview />} />
                        <Route path="agents" element={<AgentsDashboard />} />
                        <Route path="agents/:agentId" element={<AgentDetail />} />
                        <Route path="conductor" element={<ConductorPage />} />
                        <Route path="runtimes" element={<RuntimesDashboard />} />
                        <Route path="runs" element={<RunsDashboard />} />
                        <Route path="runs/:runId" element={<RunDetail />} />
                        <Route path="settings" element={<ForgeSettings />} />
                    </Route>

                    {/* Phase-0 token smoke (dev only — not linked from chrome) */}
                    <Route path="/dev/glow" element={<DevGlow />} />

                    {/* Catch-all */}
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
        </AuthProvider>
    );
}
