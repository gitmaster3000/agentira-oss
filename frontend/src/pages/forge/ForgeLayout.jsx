import React from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from '../../components/Navbar';
import { ForgeSidebar } from '../../components/ForgeSidebar';
import { FloatingChat } from '../../components/FloatingChat';

export function ForgeLayout() {
    return (
        <div className="flex flex-col h-screen overflow-hidden bg-bg-app">
            {/* AP-144/145: Forge is project-agnostic — hide the Project
                switcher (which had a dead Create-Project item here too). */}
            <Navbar onNewProject={() => {}} showProjectSwitcher={false} />

            <div className="flex flex-1 overflow-hidden">
                <ForgeSidebar />

                <main className="flex-1 overflow-auto relative flex flex-col">
                    <Outlet />
                </main>
            </div>

            <FloatingChat />
        </div>
    );
}
