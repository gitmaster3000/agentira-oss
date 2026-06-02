import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from './Navbar';
import { Sidebar } from './Sidebar';
import { CreateProjectWizard } from './CreateProjectWizard';
import { FloatingChat } from './FloatingChat';

export function Layout() {
    const [showCreate, setShowCreate] = useState(false);

    const handleProjectSuccess = () => {
        // Just close — the wizard navigates to the new project's board itself.
        // A full reload here would cancel that client-side navigation.
        setShowCreate(false);
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
