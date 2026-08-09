import React from 'react';
import { createPortal } from 'react-dom';

export function ConfirmModal({ title, message, confirmText = "Confirm", cancelText = "Cancel", onConfirm, onCancel, isDanger = true }) {
    if (typeof document === 'undefined') return null;

    return createPortal(
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/40 backdrop-blur-sm"
                onClick={onCancel}
            />

            {/* Modal */}
            <div className="relative bg-bg-card border border-border-subtle rounded-lg shadow-elevation-3 w-full max-w-sm overflow-hidden animate-fade-in">
                <div className="p-6">
                    <h2 className="text-title-lg font-medium text-text-primary mb-2">{title}</h2>
                    <p className="text-body-md text-text-secondary">{message}</p>
                </div>

                <div className="px-6 py-4 border-t flex justify-end gap-3" style={{ backgroundColor: 'var(--bg-panel)' }}>
                    <button
                        onClick={onCancel}
                        className="btn btn-ghost"
                    >
                        {cancelText}
                    </button>
                    <button
                        onClick={onConfirm}
                        className={`btn ${isDanger ? 'bg-red-600 text-white hover:bg-red-500' : 'btn-primary'}`}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>,
        document.body
    );
}
