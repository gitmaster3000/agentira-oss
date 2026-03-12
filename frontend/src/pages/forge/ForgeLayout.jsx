import React from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from '../../components/Navbar';
import { ForgeSidebar } from '../../components/ForgeSidebar';

export function ForgeLayout() {
    return (
        <div className="flex flex-col h-screen overflow-hidden bg-bg-app">
            <Navbar onNewProject={() => {}} />

            <div className="flex flex-1 overflow-hidden">
                <ForgeSidebar />

                <main className="flex-1 overflow-auto relative flex flex-col">
                    <Outlet />
                </main>
            </div>
        </div>
    );
}
