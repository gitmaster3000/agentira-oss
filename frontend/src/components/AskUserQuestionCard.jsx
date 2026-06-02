import React, { useState } from 'react';
import { HelpCircle, Send } from 'lucide-react';

/**
 * One question + its options. Read-only when `onAnswer` is absent (e.g. run
 * history); interactive when provided — clicking a choice (or typing under
 * "Something else") answers by calling `onAnswer(text)`.
 */
function QuestionBlock({ q, onAnswer }) {
    const interactive = typeof onAnswer === 'function';
    const options = Array.isArray(q.options) ? q.options : [];
    const [selected, setSelected] = useState([]);     // multiSelect picks
    const [otherOpen, setOtherOpen] = useState(false);
    const [otherText, setOtherText] = useState('');

    const toggle = (label) => setSelected((prev) =>
        prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]);

    const submitMulti = () => {
        const parts = [...selected];
        if (otherText.trim()) parts.push(otherText.trim());
        if (parts.length) onAnswer(parts.join(', '));
    };
    const submitOther = () => {
        if (otherText.trim()) onAnswer(otherText.trim());
    };

    const optionBase = 'flex gap-2 rounded-md border px-2.5 py-1.5 text-left w-full';

    return (
        <div className="rounded-lg border border-border-subtle bg-bg-app/40 p-3">
            <div className="flex items-center gap-2 mb-1.5">
                <HelpCircle className="w-3.5 h-3.5 text-accent-primary shrink-0" />
                {q.header && (
                    <span className="text-[10px] uppercase tracking-wide font-semibold text-accent-primary bg-accent-primary/10 px-1.5 py-0.5 rounded">
                        {q.header}
                    </span>
                )}
                {q.multiSelect && (
                    <span className="text-[10px] text-text-tertiary">select one or more</span>
                )}
            </div>
            {q.question && (
                <p className="text-sm text-text-primary font-medium mb-2 whitespace-pre-wrap break-words">
                    {q.question}
                </p>
            )}
            <div className="space-y-1.5">
                {options.map((opt, oi) => {
                    const isSel = selected.includes(opt.label);
                    const body = (
                        <>
                            <span className="text-text-tertiary text-xs mt-0.5 shrink-0">
                                {q.multiSelect ? (isSel ? '☑' : '☐') : `${oi + 1}.`}
                            </span>
                            <div className="min-w-0">
                                <div className="text-sm text-text-primary font-medium break-words">{opt.label}</div>
                                {opt.description && (
                                    <div className="text-xs text-text-secondary mt-0.5 whitespace-pre-wrap break-words">
                                        {opt.description}
                                    </div>
                                )}
                            </div>
                        </>
                    );
                    if (!interactive) {
                        return (
                            <div key={oi} className={`${optionBase} border-border-subtle/50 bg-bg-panel`}>
                                {body}
                            </div>
                        );
                    }
                    return (
                        <button
                            key={oi}
                            type="button"
                            onClick={() => (q.multiSelect ? toggle(opt.label) : onAnswer(opt.label))}
                            className={`${optionBase} transition-colors hover:border-accent-primary/60 hover:bg-accent-primary/5 ${
                                isSel ? 'border-accent-primary bg-accent-primary/10' : 'border-border-subtle/50 bg-bg-panel'
                            }`}
                        >
                            {body}
                        </button>
                    );
                })}

                {/* "Something else" — free-text answer */}
                {interactive && !otherOpen && (
                    <button
                        type="button"
                        onClick={() => setOtherOpen(true)}
                        className={`${optionBase} border-dashed border-border-subtle text-text-tertiary hover:text-text-secondary hover:border-accent-primary/60`}
                    >
                        <span className="text-xs mt-0.5 shrink-0">+</span>
                        <div className="text-sm">Something else…</div>
                    </button>
                )}
                {interactive && otherOpen && (
                    <div className="flex gap-1.5">
                        <input
                            autoFocus
                            value={otherText}
                            onChange={(e) => setOtherText(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') { e.preventDefault(); q.multiSelect ? submitMulti() : submitOther(); }
                            }}
                            placeholder="Type your answer…"
                            className="flex-1 input text-sm py-1.5"
                        />
                        <button
                            type="button"
                            onClick={() => (q.multiSelect ? submitMulti() : submitOther())}
                            disabled={!otherText.trim() && (!q.multiSelect || selected.length === 0)}
                            className="btn btn-primary py-1.5 px-2.5"
                            title="Send answer"
                        >
                            <Send className="w-3.5 h-3.5" />
                        </button>
                    </div>
                )}

                {/* multiSelect needs an explicit submit */}
                {interactive && q.multiSelect && !otherOpen && (
                    <button
                        type="button"
                        onClick={submitMulti}
                        disabled={selected.length === 0}
                        className="btn btn-primary py-1.5 px-3 text-sm w-full justify-center"
                    >
                        Submit {selected.length > 0 ? `(${selected.length})` : ''}
                    </button>
                )}
            </div>
        </div>
    );
}

/**
 * Render an `AskUserQuestion` tool call's structured payload readably.
 * `toolInput` is the tool input as a JSON string (or parsed object). When
 * `onAnswer(text)` is provided the choices become clickable and a free-text
 * "Something else" option is offered; otherwise it renders read-only.
 *
 * Falls back to raw text if the payload can't be parsed.
 */
export function AskUserQuestionCard({ toolInput, onAnswer }) {
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
                <QuestionBlock key={qi} q={q} onAnswer={onAnswer} />
            ))}
        </div>
    );
}

/**
 * Render a tool call's input — the structured card for tools that have one
 * (currently AskUserQuestion), else a collapsible raw <pre>. Single place that
 * owns the "which renderer for this tool" decision so the chat + run views
 * stay consistent. `onAnswer` is threaded through to make question choices
 * clickable where a send path exists (chat views), absent in read-only views.
 */
export function ToolInput({ toolName, toolInput, onAnswer }) {
    if (toolName === 'AskUserQuestion') {
        return <AskUserQuestionCard toolInput={toolInput} onAnswer={onAnswer} />;
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
