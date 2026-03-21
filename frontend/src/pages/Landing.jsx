import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';

export function Landing() {
    const { loginWithOAuth } = useAuth();
    const navigate = useNavigate();
    const [authConfig, setAuthConfig] = useState({ google: false, github: false });
    const googleBtnRef = useRef(null);
    const [error, setError] = useState('');

    useEffect(() => {
        api.getAuthConfig().then(setAuthConfig).catch(() => {});
    }, []);

    useEffect(() => {
        if (!authConfig.google || !window.google?.accounts?.id) return;
        window.google.accounts.id.initialize({
            client_id: authConfig.google_client_id,
            callback: handleGoogleResponse,
        });
        if (googleBtnRef.current) {
            window.google.accounts.id.renderButton(googleBtnRef.current, {
                theme: 'filled_black',
                size: 'large',
                width: 300,
                text: 'continue_with',
            });
        }
    }, [authConfig.google]);

    const handleGoogleResponse = async (response) => {
        setError('');
        try {
            const data = await api.googleAuth(response.credential);
            await loginWithOAuth(data);
            navigate(ROUTES.STUDIO, { replace: true });
        } catch (err) {
            setError('Google sign-in failed');
        }
    };

    const handleGitHub = () => {
        if (!authConfig.github_client_id) return;
        const redirect = `${window.location.origin}/auth/github/callback`;
        window.location.href = `https://github.com/login/oauth/authorize?client_id=${authConfig.github_client_id}&redirect_uri=${encodeURIComponent(redirect)}&scope=user:email`;
    };

    return (
        <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
            {/* Nav */}
            <nav className="flex items-center justify-between px-8 py-5 max-w-6xl mx-auto w-full">
                <div className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                    Flowty
                </div>
                <div className="flex items-center gap-3">
                    <Link
                        to={ROUTES.LOGIN}
                        className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
                    >
                        Sign In
                    </Link>
                    <Link
                        to={ROUTES.SIGNUP}
                        className="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
                    >
                        Get Started
                    </Link>
                </div>
            </nav>

            {/* Hero */}
            <main className="flex-1 flex flex-col items-center justify-center px-8 -mt-16">
                <div className="max-w-2xl text-center space-y-6">
                    <h1 className="text-5xl sm:text-6xl font-bold leading-tight">
                        Task management for
                        <span className="bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent"> humans & AI agents</span>
                    </h1>
                    <p className="text-lg text-gray-400 max-w-lg mx-auto">
                        Flowty gives your team and AI agents a shared workspace to plan, track, and ship together. Built for the way modern teams actually work.
                    </p>

                    {error && (
                        <div className="p-3 text-sm text-red-400 bg-red-900/20 border border-red-800 rounded max-w-sm mx-auto">
                            {error}
                        </div>
                    )}

                    {/* CTA Buttons */}
                    <div className="flex flex-col items-center gap-4 pt-4">
                        <Link
                            to={ROUTES.SIGNUP}
                            className="px-8 py-3 text-base font-semibold bg-blue-600 hover:bg-blue-500 text-white rounded-lg shadow-lg shadow-blue-600/20 transition-all hover:shadow-blue-500/30"
                        >
                            Get Started Free
                        </Link>

                        {/* OAuth options */}
                        {(authConfig.google || authConfig.github) && (
                            <div className="flex flex-col items-center gap-3 pt-2">
                                <span className="text-xs text-gray-500">or continue with</span>
                                <div className="flex items-center gap-3">
                                    {authConfig.google && (
                                        <div ref={googleBtnRef} />
                                    )}
                                    {authConfig.github && (
                                        <button
                                            onClick={handleGitHub}
                                            className="flex items-center gap-2 px-5 py-2.5 bg-gray-800 hover:bg-gray-700 text-white text-sm font-medium rounded-lg border border-gray-700 transition-colors"
                                        >
                                            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                                            GitHub
                                        </button>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Feature highlights */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-20 max-w-3xl w-full">
                    <div className="p-5 rounded-xl bg-gray-900/50 border border-gray-800">
                        <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center mb-3">
                            <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
                        </div>
                        <h3 className="font-semibold text-white mb-1">Kanban Boards</h3>
                        <p className="text-sm text-gray-400">Drag-and-drop task management with full lifecycle tracking.</p>
                    </div>
                    <div className="p-5 rounded-xl bg-gray-900/50 border border-gray-800">
                        <div className="w-9 h-9 rounded-lg bg-purple-500/10 flex items-center justify-center mb-3">
                            <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19 14.5M14.25 3.104c.251.023.501.05.75.082M19 14.5l-1.5 4.5H6.5L5 14.5m14 0H5" /></svg>
                        </div>
                        <h3 className="font-semibold text-white mb-1">AI-Native</h3>
                        <p className="text-sm text-gray-400">Built-in MCP server lets AI agents manage tasks alongside your team.</p>
                    </div>
                    <div className="p-5 rounded-xl bg-gray-900/50 border border-gray-800">
                        <div className="w-9 h-9 rounded-lg bg-pink-500/10 flex items-center justify-center mb-3">
                            <svg className="w-5 h-5 text-pink-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
                        </div>
                        <h3 className="font-semibold text-white mb-1">Team RBAC</h3>
                        <p className="text-sm text-gray-400">Granular roles and permissions for every member and agent.</p>
                    </div>
                </div>
            </main>

            {/* Footer */}
            <footer className="py-6 text-center text-xs text-gray-600">
                Built for AI-Human collaboration
            </footer>
        </div>
    );
}
