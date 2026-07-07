import React from 'react';
import { FileCode2 } from 'lucide-react';
import { renderStarlark } from '../../lib/workflowRules';

/** Read-only Starlark preview of the selected column's rule (plan v4 §11 shape). */
export function RuleCodePane({ columnName, flow }) {
    const source = renderStarlark(columnName, flow);
    return (
        <div className="rounded-lg border border-border-subtle overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border-subtle bg-bg-card">
                <FileCode2 className="w-3.5 h-3.5 text-tertiary" />
                <span className="text-label-md text-secondary">{columnName}.star</span>
                <span className="text-label-sm text-tertiary ml-auto">read-only preview</span>
            </div>
            <pre
                className="m-0 p-4 text-body-sm overflow-x-auto font-mono leading-relaxed"
                style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}
            >
                <code>{source}</code>
            </pre>
        </div>
    );
}
