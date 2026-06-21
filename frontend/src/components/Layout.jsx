import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { AppSidebar } from './shell/AppSidebar';
import { AppTopbar } from './shell/AppTopbar';
import { ShellDataProvider } from './shell/shellData';
import { CreateProjectWizard } from './CreateProjectWizard';
import { FloatingChat } from './FloatingChat';
import { PulseDock } from './PulseDock';
import './shell/shell.css';

export function Layout() {
    const [showCreate, setShowCreate] = useState(false);

    const handleProjectSuccess = () => {
        // Just close — the wizard navigates to the new project's board itself.
        // A full reload here would cancel that client-side navigation.
        setShowCreate(false);
    };

    return (
        <ShellDataProvider>
            <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: '#0e1117' }}>
                <AppSidebar />
                <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <AppTopbar onNewProject={() => setShowCreate(true)} />
                    <div style={{ flex: 1, overflowY: 'auto', minWidth: 0, minHeight: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
                        <Outlet />
                    </div>
                </main>

                {showCreate && <CreateProjectWizard onClose={() => setShowCreate(false)} onSuccess={handleProjectSuccess} />}

                <PulseDock />
                <FloatingChat />
            </div>
        </ShellDataProvider>
    );
}
