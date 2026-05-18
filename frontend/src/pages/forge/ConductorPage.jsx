import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
    Radio, Power, Clock, RefreshCw, ListChecks, FileText, Bot,
    CheckCircle, AlertTriangle,
} from 'lucide-react';
import { api } from '../../api';

const POLL_MS = 5000;

/**
 * ConductorPage — manage the Conductor: enable/disable, cadence config,
 * run-now controls, live status, and its recent reports / planning turns.
 */
export function ConductorPage() {
    const [data, setData] = useState(null);
    const [messages, setMessages] = useState([]);
    const [form, setForm] = useState(null);
    const [saving, setSaving] = useState(false);
    const [busy, setBusy] = useState('');      // which run-now action is in flight
    const [msg, setMsg] = useState('');

    const load = useCallback(async () => {
        try {
            const d = await api.forge.getConductor();
            setData(d);
            setForm((prev) => prev || {
                conductor_tick_seconds: d.config?.tick_seconds ?? 60,
                conductor_plan_interval_minutes: d.config?.plan_interval_minutes ?? 10,
                conductor_report_time: d.config?.report_time || '09:00',
                conductor_report_enabled: d.config?.report_enabled ?? true,
            });
            if (d.conductor?.id) {
                api.forge.listMessages(d.conductor.id, {
                    limit: 40, scope_key: 'chat:default',
                }).then((m) => Array.isArray(m) && setMessages(m)).catch(() => {});
            }
        } catch (err) {
            console.error('Failed to load conductor:', err);
        }
    }, []);

    useEffect(() => {
        load();
        const t = setInterval(load, POLL_MS);
        return () => clearInterval(t);
    }, [load]);

    if (!data) {
        return <div className="flex-1 flex items-center justify-center text-text-tertiary">Loading Conductor…</div>;
    }

    const conductorId = data.conductor?.id;
    const cfg = data.config || {};
    const active = !!cfg.active;

    const patch = async (fields) => {
        if (!conductorId) return;
        await api.forge.updateAgent(conductorId, fields);
        await load();
    };

    const toggleActive = async () => {
        try {
            await patch({ conductor_active: !active });
        } catch (err) {
            setMsg('Error: ' + (err.message || err));
        }
    };

    const saveCadence = async () => {
        setSaving(true);
        setMsg('');
        try {
            await patch(form);
            setMsg('Saved');
            setTimeout(() => setMsg(''), 2000);
        } catch (err) {
            setMsg('Error: ' + (err.message || err));
        } finally {
            setSaving(false);
        }
    };

    const runNow = async (kind) => {
        setBusy(kind);
        setMsg('');
        try {
            const fn = kind === 'tick' ? api.forge.runConductorTick
                : kind === 'plan' ? api.forge.runConductorPlan
                : api.forge.runConductorReport;
            const res = await fn();
            setMsg(`${kind}: ${res.skipped ? 'skipped — ' + res.skipped
                : res.error ? 'error — ' + res.error : 'done'}`);
            await load();
        } catch (err) {
            setMsg(`${kind} failed: ` + (err.message || err));
        } finally {
            setBusy('');
        }
    };

    return (
        <div className="flex-1 p-6 space-y-6 max-w-4xl">
            {/* Header + master switch */}
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-accent-subtle flex items-center justify-center">
                    <Radio className="w-5 h-5 text-accent-primary" />
                </div>
                <div className="flex-1">
                    <h1 className="text-2xl font-bold text-text-primary">Conductor</h1>
                    <p className="text-sm text-text-secondary">
                        Orchestrates task assignment + dispatch across the workspace.
                        {!data.conductor?.runtime_bound &&
                            ' — no runtime bound; LLM turns are paused.'}
                    </p>
                </div>
                <button
                    onClick={toggleActive}
                    className={`btn ${active ? 'btn-ghost text-emerald-400' : 'btn-ghost text-text-tertiary'}`}
                    title={active ? 'Conductor is active — click to disable' : 'Conductor is off — click to enable'}
                >
                    <Power className="w-4 h-4" />
                    {active ? 'Active' : 'Disabled'}
                </button>
            </div>

            {!active && (
                <div className="card bg-yellow-500/5 border border-yellow-500/20 text-sm text-yellow-500">
                    The Conductor is disabled — the queue tick, planning turn, and daily report are all paused.
                </div>
            )}

            {/* Status */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <StatusCard icon={RefreshCw} title="Queue tick"
                    detail={tickSummary(data.last_tick)} />
                <StatusCard icon={ListChecks} title="Planning turn"
                    detail={planSummary(data.last_plan)} />
                <StatusCard icon={FileText} title="Daily report"
                    detail={reportSummary(data.last_report)} />
            </div>

            {/* Run now */}
            <div className="card space-y-3">
                <h2 className="text-sm font-semibold text-text-primary">Run now</h2>
                <div className="flex flex-wrap gap-2">
                    <button className="btn btn-ghost" disabled={!!busy}
                        onClick={() => runNow('tick')}>
                        <RefreshCw className={`w-4 h-4 ${busy === 'tick' ? 'animate-spin' : ''}`} />
                        Queue tick
                    </button>
                    <button className="btn btn-ghost" disabled={!!busy}
                        onClick={() => runNow('plan')}>
                        <ListChecks className="w-4 h-4" /> Planning turn
                    </button>
                    <button className="btn btn-ghost" disabled={!!busy}
                        onClick={() => runNow('report')}>
                        <FileText className="w-4 h-4" /> Daily report
                    </button>
                    {msg && <span className={`text-sm self-center ${msg.startsWith('Error') || msg.includes('failed') ? 'text-red-400' : 'text-text-secondary'}`}>{msg}</span>}
                </div>
            </div>

            {/* Cadence */}
            <div className="card space-y-4">
                <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                    <Clock className="w-4 h-4" /> Cadence
                </h2>
                <div className="grid grid-cols-2 gap-4">
                    <Field label="Queue-tick interval (seconds)" hint="Deterministic dispatch — token-free.">
                        <input type="number" min="10" className="input"
                            value={form.conductor_tick_seconds}
                            onChange={(e) => setForm({ ...form, conductor_tick_seconds: Number(e.target.value) })} />
                    </Field>
                    <Field label="Planning interval (minutes)" hint="LLM turn — assigns unassigned todo work.">
                        <input type="number" min="1" className="input"
                            value={form.conductor_plan_interval_minutes}
                            onChange={(e) => setForm({ ...form, conductor_plan_interval_minutes: Number(e.target.value) })} />
                    </Field>
                    <Field label="Daily report time (UTC, HH:MM)">
                        <input type="time" className="input"
                            value={form.conductor_report_time}
                            onChange={(e) => setForm({ ...form, conductor_report_time: e.target.value })} />
                    </Field>
                    <label className="flex items-end gap-2 text-sm text-text-secondary cursor-pointer pb-2">
                        <input type="checkbox" checked={form.conductor_report_enabled}
                            onChange={(e) => setForm({ ...form, conductor_report_enabled: e.target.checked })} />
                        Compile a daily report
                    </label>
                </div>
                <button className="btn btn-primary" onClick={saveCadence} disabled={saving}>
                    {saving ? 'Saving…' : 'Save cadence'}
                </button>
            </div>

            {/* Managed agents */}
            <div className="card space-y-2">
                <h2 className="text-sm font-semibold text-text-primary">Conductor-managed agents</h2>
                {(data.survey?.agents || []).length === 0 ? (
                    <p className="text-sm text-text-tertiary">
                        No agents have Conductor management enabled. Turn it on per agent
                        in <Link to="/forge/agents" className="text-accent-primary hover:underline">Agents</Link> → Config → Conductor.
                    </p>
                ) : (
                    <div className="space-y-1">
                        {data.survey.agents.map((a) => (
                            <div key={a.agent} className="flex items-center gap-2 text-sm px-2 py-1.5 rounded bg-bg-hover">
                                <Bot className="w-3.5 h-3.5 text-text-tertiary" />
                                <Link to={`/forge/agents/${a.agent}`} className="text-accent-primary hover:underline">{a.name}</Link>
                                <span className="text-text-tertiary">{a.in_flight}/{a.capacity} in flight</span>
                                <span className="ml-auto text-text-tertiary truncate max-w-[50%]">
                                    {a.next_task ? `next: ${a.next_task.title}` : 'idle'}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Recent reports / planning turns */}
            <div className="card space-y-3">
                <h2 className="text-sm font-semibold text-text-primary">Recent reports &amp; planning turns</h2>
                {messages.length === 0 ? (
                    <p className="text-sm text-text-tertiary">No Conductor activity yet.</p>
                ) : (
                    <div className="space-y-3 max-h-[480px] overflow-y-auto">
                        {[...messages].reverse().map((m) => <ConductorMsg key={m.id} m={m} />)}
                    </div>
                )}
            </div>
        </div>
    );
}

function tickSummary(t) {
    if (!t) return 'not run yet';
    if (t.skipped) return `skipped — ${t.skipped}`;
    const d = (t.dispatched || []).length;
    const r = (t.reconciled || []).length;
    return `${d} dispatched${r ? `, ${r} reconciled` : ''}`;
}
function planSummary(p) {
    if (!p) return 'not run yet';
    if (p.skipped) return `skipped — ${p.skipped}`;
    if (p.error) return `error — ${p.error}`;
    return `${p.unassigned} task(s) sent to plan`;
}
function reportSummary(r) {
    if (!r) return 'not run yet';
    if (r.skipped) return `skipped — ${r.skipped}`;
    if (r.error) return `error — ${r.error}`;
    return r.at ? `last: ${new Date(r.at).toLocaleString()}` : 'done';
}

function StatusCard({ icon: Icon, title, detail }) {
    return (
        <div className="card flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-bg-hover flex items-center justify-center flex-shrink-0">
                <Icon className="w-4 h-4 text-text-secondary" />
            </div>
            <div className="min-w-0">
                <div className="text-sm font-medium text-text-primary">{title}</div>
                <div className="text-xs text-text-tertiary">{detail}</div>
            </div>
        </div>
    );
}

function Field({ label, hint, children }) {
    return (
        <div>
            <label className="block text-xs text-text-tertiary mb-1">{label}</label>
            {children}
            {hint && <p className="text-xs text-text-tertiary mt-1">{hint}</p>}
        </div>
    );
}

function ConductorMsg({ m }) {
    const role = m.role || 'assistant';
    const isPrompt = role === 'user';
    const label = isPrompt
        ? ((m.content || '').startsWith('QUEUE PLANNING') ? 'Planning turn'
            : (m.content || '').startsWith('DAILY REPORT') ? 'Daily report' : 'Prompt')
        : role === 'assistant' ? 'Conductor' : role;
    return (
        <div className="text-sm">
            <div className="flex items-center gap-2 mb-0.5">
                <span className="text-xs font-semibold text-text-secondary">{label}</span>
                {m.created_at && (
                    <span className="text-xs text-text-tertiary">{new Date(m.created_at).toLocaleString()}</span>
                )}
            </div>
            <pre className={`whitespace-pre-wrap break-words font-sans text-sm rounded-md p-3 border border-border-subtle/40 ${
                isPrompt ? 'bg-bg-hover/40 text-text-tertiary' : 'bg-bg-hover text-text-primary'
            }`}>
                {(m.content || '(empty)').slice(0, 4000)}
            </pre>
        </div>
    );
}
