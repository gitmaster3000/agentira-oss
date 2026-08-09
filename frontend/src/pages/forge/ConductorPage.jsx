import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
    Radio, Power, Clock, RefreshCw, ListChecks, FileText, Bot,
    CheckCircle, AlertTriangle, Download, ChevronDown, ChevronRight,
} from 'lucide-react';
import { api } from '../../api';

const POLL_MS = 5000;

// Executive-report styling for the Conductor's HTML daily report. Scoped
// under `.daily-report-host` so it applies whether or not the LLM kept the
// `daily-report` class, and reused verbatim by the standalone PDF window.
const REPORT_CSS = `
.daily-report-host{background:#fff;color:#1a1d24;font-family:Georgia,'Times New Roman',serif;line-height:1.55;padding:30px 34px;}
.daily-report-host h1{font-size:25px;margin:0 0 4px;font-weight:700;letter-spacing:-.01em;color:#0f172a;}
.daily-report-host .subtitle{margin:0 0 22px;color:#64748b;font-size:12px;font-family:system-ui,-apple-system,sans-serif;text-transform:uppercase;letter-spacing:.09em;}
.daily-report-host h2{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:#334155;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin:26px 0 10px;font-family:system-ui,-apple-system,sans-serif;}
.daily-report-host .kpis{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 6px;}
.daily-report-host .kpi{flex:1 1 110px;background:#f8fafc;border:1px solid #e9edf2;border-radius:8px;padding:13px 14px;text-align:center;}
.daily-report-host .kpi-value{font-size:28px;font-weight:700;color:#0f172a;font-family:system-ui,-apple-system,sans-serif;}
.daily-report-host .kpi-label{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-top:3px;font-family:system-ui,-apple-system,sans-serif;}
.daily-report-host ul,.daily-report-host ol{margin:8px 0;padding-left:22px;}
.daily-report-host li{margin:5px 0;}
.daily-report-host p{margin:8px 0;}
.daily-report-host strong{color:#0f172a;}
.daily-report-host table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;}
.daily-report-host th,.daily-report-host td{border:1px solid #e2e8f0;padding:7px 10px;text-align:left;}
.daily-report-host th{background:#f1f5f9;font-family:system-ui,-apple-system,sans-serif;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#475569;}
`;

// The Conductor emits its daily report as an HTML fragment. It's our own
// system agent, but an LLM can still drift — sanitize to a strict tag
// whitelist (class is the only kept attribute; script/style stripped).
const REPORT_TAGS = new Set([
    'SECTION', 'DIV', 'H1', 'H2', 'H3', 'P', 'UL', 'OL', 'LI', 'STRONG',
    'EM', 'SPAN', 'BR', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD',
]);
const DROP_TAGS = new Set([
    'SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META',
]);

function sanitizeEl(node) {
    [...node.childNodes].forEach((child) => {
        if (child.nodeType === 3) return;                   // text — keep
        if (child.nodeType !== 1) { child.remove(); return; } // comment etc.
        if (DROP_TAGS.has(child.tagName)) { child.remove(); return; }
        sanitizeEl(child);                                  // descendants first
        if (!REPORT_TAGS.has(child.tagName)) {
            child.replaceWith(...child.childNodes);         // unwrap, keep text
            return;
        }
        [...child.attributes].forEach((a) => {
            if (a.name !== 'class') child.removeAttribute(a.name);
        });
    });
}

/** Return sanitized report HTML if `raw` is an HTML report fragment, else null. */
function prepareReport(raw) {
    let html = (raw || '').trim();
    const fence = html.match(/^```(?:html)?\s*([\s\S]*?)\s*```$/i);
    if (fence) html = fence[1].trim();
    if (!/^<section\b/i.test(html)) return null;
    const doc = new DOMParser().parseFromString(html, 'text/html');
    sanitizeEl(doc.body);
    return doc.body.innerHTML;
}

/** Open the report in a standalone executive-styled page and offer PDF print. */
function openReportPdf(safeHtml, at) {
    const w = window.open('', '_blank');
    if (!w) return;
    const stamp = at ? new Date(at).toLocaleString() : '';
    w.document.write(`<!doctype html><html><head><meta charset="utf-8">`
        + `<title>Daily Report${stamp ? ' — ' + stamp : ''}</title><style>`
        + `body{margin:0;background:#eef1f4;padding:32px;}`
        + REPORT_CSS
        + `.daily-report-host{max-width:780px;margin:0 auto;border-radius:10px;`
        + `box-shadow:0 1px 6px rgba(0,0,0,.12);}`
        + `.pdf-bar{max-width:780px;margin:0 auto 14px;text-align:right;`
        + `font-family:system-ui,-apple-system,sans-serif;}`
        + `.pdf-bar button{background:#0f172a;color:#fff;border:0;border-radius:6px;`
        + `padding:9px 18px;font-size:13px;cursor:pointer;}`
        + `@media print{body{background:#fff;padding:0;}.pdf-bar{display:none;}`
        + `.daily-report-host{box-shadow:none;max-width:none;border-radius:0;}}`
        + `</style></head><body>`
        + `<div class="pdf-bar"><button onclick="window.print()">Save as PDF</button></div>`
        + `<div class="daily-report-host">${safeHtml}</div></body></html>`);
    w.document.close();
}

/**
 * ConductorPage — manage the Conductor: enable/disable, cadence config,
 * run-now controls, live status, and its recent reports / planning turns.
 */
export function ConductorPage() {
    const [data, setData] = useState(null);
    const [messages, setMessages] = useState([]);
    const [planningTurns, setPlanningTurns] = useState([]);
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
            api.forge.getPlanningTurns(20)
                .then((r) => setPlanningTurns(r?.planning_turns || []))
                .catch(() => {});
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
            // The tick returns {dispatched, skipped:[…], reconciled};
            // plan/report return {ok} | {skipped:"reason"} | {error}.
            let m;
            if (res.error) m = `error — ${res.error}`;
            else if (kind === 'tick') m = tickSummary(res);
            else if (res.skipped) m = `skipped — ${res.skipped}`;
            else m = 'done';
            setMsg(`${kind}: ${m}`);
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

            {/* AP-401: transparency feed — every planning turn, auditable */}
            <div className="card space-y-2">
                <h2 className="text-sm font-semibold text-text-primary">Planning turns</h2>
                <p className="text-xs text-text-tertiary">
                    Every planning turn's facts and decisions, durably recorded — no more SSH-ing into logs.
                </p>
                {planningTurns.length === 0 ? (
                    <p className="text-sm text-text-tertiary">No planning turns recorded yet.</p>
                ) : (
                    <div className="space-y-1 max-h-[420px] overflow-y-auto">
                        {planningTurns.map((t) => <PlanningTurnRow key={t.id} turn={t} />)}
                    </div>
                )}
            </div>

            {/* Recent reports / planning turns */}
            <div className="card space-y-3">
                <style>{REPORT_CSS}</style>
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

const STATUS_STYLE = {
    dispatched: 'text-accent-primary',
    skipped: 'text-text-tertiary',
    error: 'text-red-400',
};

function PlanningTurnRow({ turn }) {
    const [open, setOpen] = useState(false);
    const decisions = turn.decisions || [];
    const facts = turn.facts_snapshot || {};
    const taskCount = (facts.unassigned_tasks || []).length;
    const agentCount = (facts.agents || []).length;

    return (
        <div className="rounded-md border border-border-subtle/40">
            <button
                className="w-full flex items-center gap-2 px-2 py-1.5 text-sm hover:bg-bg-hover"
                onClick={() => setOpen((v) => !v)}
            >
                {open ? <ChevronDown className="w-3.5 h-3.5 text-text-tertiary" />
                    : <ChevronRight className="w-3.5 h-3.5 text-text-tertiary" />}
                <span className={`font-medium ${STATUS_STYLE[turn.status] || ''}`}>{turn.status}</span>
                <span className="text-text-tertiary">
                    {turn.created_at ? new Date(turn.created_at).toLocaleString() : ''}
                </span>
                <span className="text-text-tertiary">
                    {agentCount} agent(s), {taskCount} task(s) seen
                </span>
                {decisions.length > 0 && (
                    <span className="text-text-tertiary">— {decisions.length} decision(s)</span>
                )}
                <span className="ml-auto text-text-tertiary text-xs">
                    {turn.model || ''}{turn.duration_ms != null ? ` · ${turn.duration_ms}ms` : ''}
                    {turn.token_cost != null ? ` · $${turn.token_cost.toFixed(4)}` : ''}
                </span>
            </button>
            {open && (
                <div className="px-3 pb-2 space-y-1.5 text-sm">
                    {decisions.length === 0 ? (
                        <p className="text-text-tertiary">
                            No decisions recorded yet
                            {turn.conversation_scope_key ? ' — full transcript below.' : '.'}
                        </p>
                    ) : (
                        decisions.map((d, i) => (
                            <div key={i} className="text-text-secondary">
                                <span className="font-medium text-text-primary">{d.action}</span>
                                {d.agent ? ` → ${d.agent}` : ''}
                                {d.task_id ? (
                                    <>
                                        {' '}
                                        <Link to={`/studio/tasks/${d.task_id}`} className="text-accent-primary hover:underline">
                                            task
                                        </Link>
                                    </>
                                ) : ''}
                                {d.reason ? ` — ${d.reason}` : ''}
                            </div>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}

function tickSummary(t) {
    if (!t) return 'not run yet';
    if (t.disabled) return 'conductor disabled';
    const d = (t.dispatched || []).length;
    // `skipped` is a list of {agent, reason} records — surface the reasons.
    const sk = Array.isArray(t.skipped) ? t.skipped : [];
    const r = (t.reconciled || []).length;
    if (!d && !sk.length && !r) return 'idle — nothing to dispatch';
    const reasons = [...new Set(sk.map((s) => s && s.reason).filter(Boolean))];
    let s = `${d} dispatched`;
    if (sk.length) {
        s += `, ${sk.length} skipped`;
        if (reasons.length) s += ` (${reasons.join(', ')})`;
    }
    if (r) s += `, ${r} reconciled`;
    return s;
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
    // An assistant turn whose content is an HTML report fragment renders as
    // a formatted executive report rather than raw text.
    const reportHtml = isPrompt ? null : prepareReport(m.content);
    const label = isPrompt
        ? ((m.content || '').startsWith('QUEUE PLANNING') ? 'Planning turn'
            : (m.content || '').startsWith('DAILY REPORT') ? 'Daily report' : 'Prompt')
        : reportHtml ? 'Daily report'
        : role === 'assistant' ? 'Conductor' : role;

    if (reportHtml) {
        return (
            <div className="text-sm">
                <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-text-secondary">{label}</span>
                    {m.created_at && (
                        <span className="text-xs text-text-tertiary">{new Date(m.created_at).toLocaleString()}</span>
                    )}
                    <button
                        className="btn btn-ghost ml-auto !py-0.5 !px-2 text-xs"
                        onClick={() => openReportPdf(reportHtml, m.created_at)}
                        title="Open in a printable page — use the browser's Save as PDF"
                    >
                        <Download className="w-3.5 h-3.5" /> Download PDF
                    </button>
                </div>
                <div
                    className="daily-report-host rounded-md overflow-hidden border border-border-subtle/40"
                    dangerouslySetInnerHTML={{ __html: reportHtml }}
                />
            </div>
        );
    }

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
