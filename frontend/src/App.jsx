import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Board } from './pages/Board';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Login } from './pages/Login';
import { Signup } from './pages/Signup';
import { GitHubCallback } from './pages/GitHubCallback';
import { Settings } from './pages/Settings';
import { TaskPage } from './pages/TaskPage';

function Welcome() {
    return (
        <div className="flex-1 flex flex-col items-center justify-center text-secondary">
            <div className="text-center">
                <h2 className="text-2xl font-bold text-primary mb-2">Welcome to Flowty Studio</h2>
                <p>Select a project from the sidebar to get started.</p>
            </div>
        </div>
    );
}

function RequireAuth({ children }) {
    const { user, loading } = useAuth();
    if (loading) return <div>Loading...</div>;
    if (!user) return <Navigate to="/login" replace />;
    return children;
}

export default function App() {
    return (
        <AuthProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/login" element={<Login />} />
                    <Route path="/signup" element={<Signup />} />
                    <Route path="/auth/github/callback" element={<GitHubCallback />} />

                    {/* Studio routes */}
                    <Route path="/" element={
                        <RequireAuth>
                            <Layout />
                        </RequireAuth>
                    }>
                        <Route index element={<Welcome />} />
                        <Route path="board" element={<Navigate to="/" replace />} />
                        <Route path="board/:projectId" element={<Board />} />
                        <Route path="settings" element={<Settings />} />
                        <Route path="tasks/:taskId" element={<TaskPage />} />
                    </Route>

                    {/* Forge routes — disabled for now */}
                    <Route path="/forge/*" element={<Navigate to="/" replace />} />
                </Routes>
            </BrowserRouter>
        </AuthProvider>
    );
}
