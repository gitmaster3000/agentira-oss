import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';
import { Pencil } from 'lucide-react';

export function Signup() {
    const [formData, setFormData] = useState({ name: '', display_name: '', password: '' });
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [authConfig, setAuthConfig] = useState({ google: false, github: false });
    const { loginWithOAuth } = useAuth();
    const navigate = useNavigate();
    const googleBtnRef = useRef(null);

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
                width: 320,
                text: 'signup_with',
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
            setError('Google sign-up failed');
        }
    };

    const handleGitHub = () => {
        if (!authConfig.github_client_id) return;
        const redirect = `${window.location.origin}${ROUTES.GITHUB_CALLBACK}`;
        window.location.href = `https://github.com/login/oauth/authorize?client_id=${authConfig.github_client_id}&redirect_uri=${encodeURIComponent(redirect)}&scope=user:email`;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await api.signup(formData);
            navigate(ROUTES.LOGIN, { state: { message: 'Account created! Please sign in.' } });
        } catch (err) {
            setError(err.message || 'Signup failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="h-full bg-bg-app flex flex-col items-center justify-center px-4 overflow-y-auto">
            <div className="w-full max-w-sm space-y-6">
                {/* Logo */}
                <Link to={ROUTES.WELCOME} className="flex items-center gap-2.5 justify-center mb-2">
                    <span className="w-9 h-9 rounded-md flex items-center justify-center" style={{ backgroundColor: 'rgba(201, 184, 255, 0.1)' }}>
                        <Pencil className="w-5 h-5" style={{ color: 'var(--accent-primary)' }} />
                    </span>
                    <div className="flex flex-col leading-tight">
                        <span className="text-[10px] font-medium tracking-widest uppercase text-text-tertiary">Flowty</span>
                        <span className="text-title-sm font-semibold text-text-primary">Studio</span>
                    </div>
                </Link>

                <div className="card space-y-5">
                    <h2 className="text-headline-sm text-text-primary text-center">Create account</h2>

                    {error && <div className="p-3 text-body-sm text-red-400 bg-red-900/20 border border-red-800 rounded-md">{error}</div>}

                    {/* OAuth */}
                    {(authConfig.google || authConfig.github) && (
                        <div className="space-y-3">
                            {authConfig.google && (
                                <div ref={googleBtnRef} className="flex justify-center" />
                            )}
                            {authConfig.github && (
                                <button
                                    onClick={handleGitHub}
                                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-body-md font-medium transition-colors border"
                                    style={{ backgroundColor: 'var(--bg-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-primary)' }}
                                >
                                    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                                    Sign up with GitHub
                                </button>
                            )}

                            <div className="relative">
                                <div className="absolute inset-0 flex items-center"><div className="w-full border-t" style={{ borderColor: 'var(--border-subtle)' }}></div></div>
                                <div className="relative flex justify-center text-label-sm"><span className="px-3 text-text-tertiary" style={{ backgroundColor: 'var(--bg-card)' }}>or</span></div>
                            </div>
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label className="text-label-md text-text-secondary mb-1 block">Username</label>
                            <input
                                type="text"
                                required
                                value={formData.name}
                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                className="input"
                                placeholder="e.g. jdoe"
                                autoFocus
                            />
                        </div>
                        <div>
                            <label className="text-label-md text-text-secondary mb-1 block">Display Name</label>
                            <input
                                type="text"
                                value={formData.display_name}
                                onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                                className="input"
                                placeholder="e.g. John Doe"
                            />
                        </div>
                        <div>
                            <label className="text-label-md text-text-secondary mb-1 block">Password</label>
                            <input
                                type="password"
                                required
                                value={formData.password}
                                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                className="input"
                                placeholder="••••••••"
                            />
                        </div>
                        <button
                            type="submit"
                            disabled={loading}
                            className="btn btn-primary w-full justify-center text-body-md"
                        >
                            {loading ? 'Creating Account...' : 'Sign Up'}
                        </button>
                    </form>

                    <p className="text-body-sm text-text-tertiary text-center">
                        Already have an account?{' '}
                        <Link to={ROUTES.LOGIN} className="font-medium" style={{ color: 'var(--accent-primary)' }}>Sign In</Link>
                    </p>
                </div>
            </div>
        </div>
    );
}
