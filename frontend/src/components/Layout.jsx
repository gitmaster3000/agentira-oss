import React, { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { AppSidebar } from './shell/AppSidebar';
import { AppTopbar } from './shell/AppTopbar';
import { ShellDataProvider } from './shell/shellData';
import { CreateProjectWizard } from './CreateProjectWizard';
import { FloatingChat } from './FloatingChat';
import { PulseDock } from './PulseDock';
import './shell/shell.css';

export function Layout() {
    const [showCreate, setShowCreate] = useState(false);
    // Mobile off-canvas nav: closed by default, toggled by the topbar hamburger.
    const [navOpen, setNavOpen] = useState(false);
    const location = useLocation();

    // Any route change (incl. project switch) closes the mobile drawer.
    useEffect(() => { setNavOpen(false); }, [location.pathname]);

    const handleProjectSuccess = () => {
        // Just close — the wizard navigates to the new project's board itself.
        // A full reload here would cancel that client-side navigation.
        setShowCreate(false);
    };

    return (
        <ShellDataProvider>
            <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: '#0e1117' }}>
                {navOpen && <div className="shell-backdrop" onClick={() => setNavOpen(false)} />}
                <AppSidebar open={navOpen} />
                <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <AppTopbar onNewProject={() => setShowCreate(true)} onMenu={() => setNavOpen((o) => !o)} />
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
