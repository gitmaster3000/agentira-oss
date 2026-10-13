import React, { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { AppSidebar } from './shell/AppSidebar';
import { AppTopbar } from './shell/AppTopbar';
import { ShellDataProvider } from './shell/shellData';
import { CreateProjectWizard } from './CreateProjectWizard';
import { FloatingChat } from './FloatingChat';
import { PulseDock } from './PulseDock';
import './shell/shell.css';

// Shell root, ported from Agentira.dc.html: a gradient canvas holding a
// blended header row, then a row of two floating panels (rail + main).
// Themed — the canvas tokens flip with day/night (tokens/colors.css).
const CANVAS = 'radial-gradient(900px 480px at 14% -10%,var(--canvas-glow-a),transparent),'
    + 'radial-gradient(1000px 520px at 86% -14%,var(--canvas-glow-b),transparent),var(--canvas-base)';

export function Layout() {
    const [showCreate, setShowCreate] = useState(false);
    // Mobile off-canvas nav: closed by default, toggled by the topbar hamburger.
    const [navOpen, setNavOpen] = useState(false);
    // Desktop rail: expanded (248px) or collapsed to icons (66px).
    const [railOpen, setRailOpen] = useState(true);
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
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', height: '100%', overflow: 'hidden', padding: '12px', background: CANVAS }}>
                <AppTopbar onNewProject={() => setShowCreate(true)} onMenu={() => setNavOpen((o) => !o)} />

                <div style={{ flex: 1, display: 'flex', gap: '12px', minHeight: 0 }}>
                    {navOpen && <div className="shell-backdrop" onClick={() => setNavOpen(false)} />}
                    <AppSidebar open={navOpen} railOpen={railOpen} onToggleRail={() => setRailOpen((o) => !o)} />
                    <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'var(--surface-base)', border: '1px solid var(--overlay-tint)', borderRadius: '16px', overflow: 'hidden', boxShadow: 'var(--shadow-panel)' }}>
                        <div style={{ flex: 1, overflowY: 'auto', minWidth: 0, minHeight: 0, position: 'relative', display: 'flex', flexDirection: 'column' }}>
                            <Outlet />
                        </div>
                    </main>
                </div>

                {showCreate && <CreateProjectWizard onClose={() => setShowCreate(false)} onSuccess={handleProjectSuccess} />}

                <PulseDock />
                <FloatingChat />
            </div>
        </ShellDataProvider>
    );
}
