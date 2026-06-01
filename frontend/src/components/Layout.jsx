import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from './Navbar';
import { Sidebar } from './Sidebar';
import { CreateProjectWizard } from './CreateProjectWizard';
import { FloatingChat } from './FloatingChat';

export function Layout() {
    const [showCreate, setShowCreate] = useState(false);

    const handleProjectSuccess = () => {
        // We might want to trigger a refresh in the Navbar's project list.
        // For now, Navbar handles its own loading.
        setShowCreate(false);
        // Refresh the page or use a shared state/context if needed to update project list everywhere
        window.location.reload();
    };

    return (
        <div className="flex flex-col h-screen overflow-hidden bg-bg-app">
            <Navbar onNewProject={() => setShowCreate(true)} />

            <div className="flex flex-1 overflow-hidden relative">
                <Sidebar />

                <main className="flex-1 overflow-hidden relative flex flex-col">
                    <Outlet />
                </main>
            </div>

            {showCreate && <CreateProjectWizard onClose={() => setShowCreate(false)} onSuccess={handleProjectSuccess} />}

            <FloatingChat />
        </div>
    );
}
