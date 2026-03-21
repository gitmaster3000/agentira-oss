import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api } from '../api';
import { ROUTES } from '../routes';

export function GitHubCallback() {
    const [error, setError] = useState('');
    const [searchParams] = useSearchParams();
    const { loginWithOAuth } = useAuth();
    const navigate = useNavigate();

    useEffect(() => {
        const code = searchParams.get('code');
        if (!code) {
            setError('No authorization code received');
            return;
        }
        api.githubAuth(code)
            .then((data) => loginWithOAuth(data))
            .then(() => navigate(ROUTES.STUDIO, { replace: true }))
            .catch(() => setError('GitHub authentication failed'));
    }, []);

    if (error) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-gray-900 text-gray-100">
                <div className="text-center space-y-4">
                    <p className="text-red-400">{error}</p>
                    <a href="/login" className="text-blue-400 hover:underline">Back to login</a>
                </div>
            </div>
        );
    }

    return (
        <div className="flex min-h-screen items-center justify-center bg-gray-900 text-gray-100">
            <p className="text-gray-400">Signing in with GitHub...</p>
        </div>
    );
}
