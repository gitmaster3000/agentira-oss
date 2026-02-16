import React, { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const stored = localStorage.getItem('agentira_user');
        if (stored) {
            setUser(JSON.parse(stored));
        }
        setLoading(false);
    }, []);

    const login = async (username, password) => {
        const data = await api.login(username, password);
        setUser(data.user);
        localStorage.setItem('agentira_user', JSON.stringify(data.user));
        return data.user;
    };

    const logout = () => {
        setUser(null);
        localStorage.removeItem('agentira_user');
    };

    const value = { user, login, logout, loading };

    return <AuthContext.Provider value={value}>{!loading && children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
