import React, { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const stored = localStorage.getItem('agentira_user');
        if (stored) {
            try {
                const parsed = JSON.parse(stored);
                // Ensure role is a string
                if (parsed && typeof parsed.role === 'object' && parsed.role.name) {
                    parsed.role = parsed.role.name;
                }
                setUser(parsed);
            } catch (e) {
                console.error('Failed to parse stored user:', e);
                localStorage.removeItem('agentira_user');
            }
        }
        setLoading(false);
    }, []);

    const login = async (username, password) => {
        const data = await api.login(username, password);
        let userToStore = data.user;
        // Normalize role if it's an object
        if (userToStore && typeof userToStore.role === 'object' && userToStore.role.name) {
            userToStore = { ...userToStore, role: userToStore.role.name };
        }
        setUser(userToStore);
        localStorage.setItem('agentira_user', JSON.stringify(userToStore));
        return userToStore;
    };

    const loginWithOAuth = async (data) => {
        let userToStore = data.user;
        if (userToStore && typeof userToStore.role === 'object' && userToStore.role.name) {
            userToStore = { ...userToStore, role: userToStore.role.name };
        }
        setUser(userToStore);
        localStorage.setItem('agentira_user', JSON.stringify(userToStore));
        return userToStore;
    };

    const logout = () => {
        setUser(null);
        localStorage.removeItem('agentira_user');
    };

    const value = { user, login, loginWithOAuth, logout, loading };

    return <AuthContext.Provider value={value}>{!loading && children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
