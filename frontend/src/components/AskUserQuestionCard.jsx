import React from 'react';
import { HelpCircle } from 'lucide-react';

/**
 * Render an `AskUserQuestion` tool call's structured payload readably —
 * the question(s), a header chip, and the options with their descriptions —
 * instead of dumping raw JSON.
 *
 * `toolInput` is the tool's input as a JSON string (or already-parsed object).
 * Shape: { questions: [{ question, header, multiSelect, options:[{label, description}] }] }
 *
 * Falls back to the raw text in a <pre> if it can't be parsed, so it never
 * renders nothing.
 */
export function AskUserQuestionCard({ toolInput }) {
    let data = null;
    try {
        data = typeof toolInput === 'string' ? JSON.parse(toolInput) : toolInput;
    } catch {
        data = null;
    }
    const questions = data && Array.isArray(data.questions) ? data.questions : null;

    if (!questions || questions.length === 0) {
        return (
            <pre className="mt-1 p-2 bg-bg-hover rounded text-xs text-text-secondary overflow-auto max-h-32 whitespace-pre-wrap">
                {typeof toolInput === 'string' ? toolInput : JSON.stringify(toolInput, null, 2)}
            </pre>
        );
    }

    return (
        <div className="mt-2 space-y-3">
            {questions.map((q, qi) => (
                <div key={qi} className="rounded-lg border border-border-subtle bg-bg-app/40 p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                        <HelpCircle className="w-3.5 h-3.5 text-accent-primary shrink-0" />
                        {q.header && (
                            <span className="text-[10px] uppercase tracking-wide font-semibold text-accent-primary bg-accent-primary/10 px-1.5 py-0.5 rounded">
                                {q.header}
                            </span>
                        )}
                        {q.multiSelect && (
                            <span className="text-[10px] text-text-tertiary">multi-select</span>
                        )}
                    </div>
                    {q.question && (
                        <p className="text-sm text-text-primary font-medium mb-2 whitespace-pre-wrap break-words">
                            {q.question}
                        </p>
                    )}
                    <div className="space-y-1.5">
                        {(q.options || []).map((opt, oi) => (
                            <div
                                key={oi}
                                className="flex gap-2 rounded-md border border-border-subtle/50 bg-bg-panel px-2.5 py-1.5"
                            >
                                <span className="text-text-tertiary text-xs mt-0.5 shrink-0">{oi + 1}.</span>
                                <div className="min-w-0">
                                    <div className="text-sm text-text-primary font-medium break-words">{opt.label}</div>
                                    {opt.description && (
                                        <div className="text-xs text-text-secondary mt-0.5 whitespace-pre-wrap break-words">
                                            {opt.description}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
}

/**
 * Render a tool call's input — the structured card for tools that have one
 * (currently AskUserQuestion), else a collapsible raw <pre>. Single place that
 * owns the "which renderer for this tool" decision so the chat + run views
 * stay consistent.
 */
export function ToolInput({ toolName, toolInput }) {
    if (toolName === 'AskUserQuestion') {
        return <AskUserQuestionCard toolInput={toolInput} />;
    }
    if (!toolInput) return null;
    return (
        <details className="text-xs mt-1">
            <summary className="text-text-tertiary cursor-pointer hover:text-text-secondary">Input</summary>
            <pre className="mt-1 p-2 bg-bg-hover rounded text-text-secondary overflow-auto max-h-32 whitespace-pre-wrap">
                {toolInput}
            </pre>
        </details>
    );
}
