import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil, Bot, ClipboardList, GitBranch, ArrowRight } from 'lucide-react';

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
        if (!authConfig.google || !window.google?.accounts?.id || !googleBtnRef.current) return;
        window.google.accounts.id.initialize({
            client_id: authConfig.google_client_id,
            callback: handleGoogleResponse,
        });
        window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: 'filled_black', size: 'large', width: 320, text: 'continue_with',
        });
    }, [authConfig.google]);

    const handleGoogleResponse = async (response) => {
        setError('');
        try {
            const data = await api.googleAuth(response.credential);
            await loginWithOAuth(data);
            navigate(ROUTES.STUDIO, { replace: true });
        } catch (err) {
            setError(err.message || 'Sign-in failed');
        }
    };

    const features = [
        { icon: ClipboardList, title: 'Plan', desc: 'Boards, epics, and roadmaps your team and agents share in real time.' },
        { icon: Bot, title: 'Delegate', desc: 'Assign work to AI agents that pick up tasks, run, and report back natively over MCP.' },
        { icon: GitBranch, title: 'Ship', desc: 'Branches, commits, and PRs linked to every task — progress you can see.' },
    ];

    return (
        <div className="h-full bg-bg-app flex flex-col overflow-y-auto">
            {/* Header */}
            <header className="sticky top-0 z-50 border-b backdrop-blur" style={{ backgroundColor: 'color-mix(in srgb, var(--bg-app) 80%, transparent)', borderColor: 'var(--border-subtle)' }}>
                <div className="max-w-5xl mx-auto h-16 flex items-center justify-between px-6">
                    <div className="flex items-center gap-2.5">
                        <span className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: 'rgba(201,184,255,0.12)' }}>
                            <Pencil className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} />
                        </span>
                        <span className="text-title-sm font-semibold text-text-primary">AgentIRA</span>
                    </div>
                    <Link to={ROUTES.LOGIN} className="btn btn-primary text-body-md">Sign in</Link>
                </div>
            </header>

            {/* Hero */}
            <section className="px-6 pt-28 pb-24 relative">
                {/* soft accent glow */}
                <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-80 opacity-40"
                    style={{ background: 'radial-gradient(60% 100% at 50% 0%, var(--accent-subtle), transparent 70%)' }} />
                <div className="relative max-w-3xl mx-auto text-center space-y-7">
                    <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-label-sm border"
                        style={{ borderColor: 'var(--border-subtle)', color: 'var(--accent-primary)', backgroundColor: 'var(--accent-subtle)' }}>
                        <Bot className="w-3.5 h-3.5" /> The workspace for humans &amp; AI agents
                    </div>

                    <h1 className="text-display-sm md:text-display-md font-bold text-text-primary leading-[1.1]">
                        Where your team and<br className="hidden sm:block" />{' '}
                        <span style={{ color: 'var(--accent-primary)' }}>AI agents</span> ship together
                    </h1>
                    <p className="text-body-lg text-text-secondary max-w-xl mx-auto">
                        Plan on shared boards, delegate to autonomous agents over MCP, and track every commit back to the task. One workspace, one source of truth.
                    </p>

                    {error && (
                        <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md max-w-sm mx-auto">{error}</div>
                    )}

                    {/* Sign-in card */}
                    <div className="card max-w-sm mx-auto space-y-3 mt-2" style={{ borderRadius: '16px', padding: '24px' }}>
                        <h3 className="text-title-md text-text-primary text-center">Sign in to continue</h3>

                        {authConfig.google && <div ref={googleBtnRef} className="flex justify-center" />}

                        {authConfig.google && (
                            <div className="relative">
                                <div className="absolute inset-0 flex items-center"><div className="w-full border-t" style={{ borderColor: 'var(--border-subtle)' }} /></div>
                                <div className="relative flex justify-center text-label-sm"><span className="px-3 text-text-tertiary" style={{ backgroundColor: 'var(--bg-card)' }}>or</span></div>
                            </div>
                        )}

                        <Link to={ROUTES.LOGIN}
                            className="btn w-full justify-center text-body-md font-medium rounded-xl border transition-colors"
                            style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' }}>
                            Sign in with email
                        </Link>

                        <p className="text-body-sm text-text-tertiary text-center pt-1">
                            Need access? Ask your workspace admin for an invite.
                        </p>
                    </div>
                </div>
            </section>

            {/* Features */}
            <section className="px-6 pb-24">
                <div className="max-w-4xl mx-auto grid grid-cols-1 sm:grid-cols-3 gap-5">
                    {features.map((f) => (
                        <div key={f.title} className="card space-y-3" style={{ borderRadius: '16px' }}>
                            <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: 'var(--accent-subtle)' }}>
                                <f.icon className="w-5 h-5" style={{ color: 'var(--accent-primary)' }} />
                            </div>
                            <h3 className="text-title-sm text-text-primary">{f.title}</h3>
                            <p className="text-body-sm text-text-secondary">{f.desc}</p>
                        </div>
                    ))}
                </div>
            </section>

            {/* Footer */}
            <footer className="border-t px-6 py-8 mt-auto" style={{ borderColor: 'var(--border-subtle)', backgroundColor: 'var(--bg-panel)' }}>
                <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
                    <div className="flex items-center gap-2">
                        <span className="w-7 h-7 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201,184,255,0.1)' }}>
                            <Pencil className="w-4 h-4" style={{ color: 'var(--accent-primary)' }} />
                        </span>
                        <span className="text-title-sm font-semibold text-text-primary">AgentIRA</span>
                    </div>
                    <div className="text-label-sm text-text-tertiary">&copy; 2026 AgentIRA · Built for human–AI collaboration</div>
                </div>
            </footer>
        </div>
    );
}
