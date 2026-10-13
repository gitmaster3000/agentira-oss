// Browser telemetry: what each user actually experiences, sent to
// POST /api/client-logs and written to the backend log as `CLIENT {json}`.
//
// Collected (no field values, no request bodies, no tokens):
// - error        uncaught errors, unhandled promise rejections, React crashes
// - interaction  a keystroke/click that took long to paint (200ms; 50ms at debug)
//                (Event Timing API, what INP measures) + which element
// - longtask     main-thread freezes >= 200ms, aggregated per flush
// - api          failed or slow (1.5s; all at debug) calls as the browser saw them
//                (server time + network); api_summary aggregates the rest
// - page_load    TTFB, DOM ready, load, LCP, bytes transferred
//
// Level (standard names): "info" everywhere; "debug" (thresholds 50ms, every
// API call, flush every 10s) when the backend switches it on for this user —
// by an admin command or automatically after a crash / >=1s interaction. The level
// comes back on every log POST and from /client-logs/config at startup.
//
// Enabled in production builds only (or VITE_TELEMETRY=1). Read with:
//   railway logs -s backend --filter "CLIENT" --since 1d
//
// Overhead budget: per API call a few additions; observers only act on
// entries that are already slow; at most one small POST a minute, sent in
// idle time with keepalive. Telemetry times itself and reports `self_ms`.

const ENDPOINT = `${import.meta.env.VITE_API_URL || '/api'}/client-logs`;
const ENABLED = import.meta.env.MODE !== 'test'
    && (import.meta.env.PROD || import.meta.env.VITE_TELEMETRY === '1');
const TICK_MS = 10_000;
const LEVELS = {
    info: { interaction: 200, longtask: 200, slowApi: 1500, flushMs: 60_000 },
    debug: { interaction: 50, longtask: 50, slowApi: 0, flushMs: 10_000 },
};
let cfg = LEVELS.info;
let level = 'info';
let lastFlush = 0;
const SUMMARY_EVERY_MS = 5 * 60_000; // routine API stats alone don't justify a POST
const MAX_QUEUE = 100;

let queue = [];
let apiAgg = {};      // endpoint -> { n, sum, max }
let longAgg = null;   // { count, max }
let started = false;
let selfMs = 0;        // CPU time spent inside telemetry itself
let lastSummary = 0;

function timed(fn) {
    return (...args) => {
        const t0 = performance.now();
        try { return fn(...args); } finally { selfMs += performance.now() - t0; }
    };
}

// Ids in paths would make every route unique; collapse them.
export function normalizePath(p) {
    return String(p || '')
        .split('?')[0]
        .replace(/\/[0-9a-f]{8,}(?=\/|$)/gi, '/:id')
        .replace(/\/[A-Z][A-Z0-9]*-\d+(?=\/|$)/g, '/:key')
        .replace(/\/[A-Za-z0-9_-]{24,}(?=\/|$)/g, '/:token');
}

const route = () => normalizePath(window.location.pathname);

function sessionId() {
    try {
        let s = sessionStorage.getItem('agentira.tsession');
        if (!s) {
            s = Math.random().toString(36).slice(2, 10);
            sessionStorage.setItem('agentira.tsession', s);
        }
        return s;
    } catch { return 'nostorage'; }
}

function push(ev) {
    if (!ENABLED || queue.length >= MAX_QUEUE) return null;
    const item = { route: route(), t: Math.round(performance.now()), ...ev };
    queue.push(item);
    return item;
}

// Short readable name for an element — tag plus its label, never its value.
function describe(el) {
    if (!el || !el.tagName) return '';
    const label = el.getAttribute?.('aria-label') || el.getAttribute?.('placeholder')
        || el.getAttribute?.('name') || el.id || (el.className && String(el.className).split(' ')[0]) || '';
    return `${el.tagName.toLowerCase()}${label ? `[${String(label).slice(0, 60)}]` : ''}`;
}

export function reportError(error, extra = {}) {
    const errorId = Math.random().toString(36).slice(2, 10);
    push({
        kind: 'error',
        message: String(error?.message || error).slice(0, 500),
        stack: String(error?.stack || '').slice(0, 2000),
        error_id: errorId,
        ...extra,
    });
    flush(true);
    return errorId;
}

// Called by api.request() for every API call.
export const recordApi = timed((method, endpoint, status, duration) => {
    if (!ENABLED) return;
    const ep = normalizePath(endpoint);
    const ok = status >= 200 && status < 400;
    if (!ok || duration >= cfg.slowApi) {
        push({ kind: 'api', method, endpoint: ep, status, duration: Math.round(duration), ok });
        return;
    }
    const key = `${method} ${ep}`;
    const a = apiAgg[key] || (apiAgg[key] = { n: 0, sum: 0, max: 0 });
    a.n += 1; a.sum += duration; a.max = Math.max(a.max, duration);
});

function context() {
    const c = navigator.connection;
    return {
        session: sessionId(),
        release: import.meta.env.VITE_RELEASE || 'dev',
        ua: navigator.userAgent,
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        net: c ? `${c.effectiveType || '?'} rtt=${c.rtt ?? '?'} down=${c.downlink ?? '?'}` : undefined,
        screen: `${window.innerWidth}x${window.innerHeight}@${window.devicePixelRatio || 1}`,
        cpu: navigator.hardwareConcurrency,
        mem: navigator.deviceMemory,
        level,
        self_ms: Math.round(selfMs),
    };
}

export const flush = timed((force = false) => {
    if (!ENABLED) return;
    const keys = Object.keys(apiAgg);
    const now = performance.now();
    const summaryDue = force || queue.length > 0 || longAgg || now - lastSummary >= SUMMARY_EVERY_MS;
    if (keys.length && summaryDue) {
        lastSummary = now;
        const endpoints = {};
        for (const k of keys) {
            const a = apiAgg[k];
            endpoints[k] = { n: a.n, avg: Math.round(a.sum / a.n), max: Math.round(a.max) };
        }
        queue.push({ kind: 'api_summary', route: route(), t: Math.round(performance.now()), endpoints });
        apiAgg = {};
    }
    if (longAgg) {
        queue.push({ kind: 'longtask', route: route(), t: Math.round(performance.now()), ...longAgg });
        longAgg = null;
    }
    if (!queue.length) return;
    lastFlush = now;
    const events = queue;
    queue = [];
    const headers = { 'Content-Type': 'application/json', ...authHeaders() };
    // keepalive lets the request finish while the tab is closing.
    fetch(ENDPOINT, {
        method: 'POST', headers, keepalive: true,
        body: JSON.stringify({ ...context(), events }),
    }).then((r) => (r.ok ? r.json() : null)).then(applyLevel).catch(() => {});
});

function applyLevel(res) {
    const next = res && LEVELS[res.level] ? res.level : null;
    if (!next || next === level) return;
    level = next;
    cfg = LEVELS[next];
}

function authHeaders() {
    try {
        const token = localStorage.getItem('agentira_token');
        return token ? { Authorization: `Bearer ${token}` } : {};
    } catch { return {}; }
}

// Periodic flushes wait for idle time so they never compete with typing.
const idle = (fn) => (window.requestIdleCallback
    ? window.requestIdleCallback(fn, { timeout: 5000 })
    : setTimeout(fn, 0));

function observe(type, cb, opts = {}) {
    try {
        if (!PerformanceObserver.supportedEntryTypes?.includes(type)) return;
        const handle = timed(cb);
        new PerformanceObserver((list) => list.getEntries().forEach(handle))
            .observe({ type, buffered: true, ...opts });
    } catch { /* unsupported browser */ }
}

export function startTelemetry() {
    if (!ENABLED || started) return;
    started = true;

    window.addEventListener('error', (e) => {
        reportError(e.error || e.message, { source: `${e.filename || ''}:${e.lineno || ''}` });
    });
    window.addEventListener('unhandledrejection', (e) => {
        reportError(e.reason, { source: 'unhandledrejection' });
    });

    // Slow interactions: time from input to the next paint. One keystroke
    // yields several entries (keydown, keypress, input...) sharing an
    // interactionId; log it once, from its longest phase (what INP counts).
    const seen = new Map(); // interactionId -> pushed event
    observe('event', (e) => {
        if (!e.interactionId || e.duration < cfg.interaction) return;
        const prev = seen.get(e.interactionId);
        if (prev) {
            if (e.duration > prev.duration) prev.duration = Math.round(e.duration);
            return;
        }
        if (seen.size > 200) seen.clear();
        const ev = {
            kind: 'interaction',
            event: e.name,
            duration: Math.round(e.duration),
            input_delay: Math.round(e.processingStart - e.startTime),
            processing: Math.round(e.processingEnd - e.processingStart),
            target: describe(e.target),
        };
        const item = push(ev);
        if (item) seen.set(e.interactionId, item);
    }, { durationThreshold: LEVELS.debug.interaction });

    observe('longtask', (e) => {
        if (e.duration < cfg.longtask) return;
        longAgg = longAgg || { count: 0, duration: 0 };
        longAgg.count += 1;
        longAgg.duration = Math.max(longAgg.duration, Math.round(e.duration));
    });

    let lcp = 0;
    observe('largest-contentful-paint', (e) => { lcp = Math.round(e.startTime); });
    window.addEventListener('load', () => {
        setTimeout(() => {
            const nav = performance.getEntriesByType('navigation')[0];
            if (!nav) return;
            const bytes = performance.getEntriesByType('resource')
                .reduce((s, r) => s + (r.transferSize || 0), nav.transferSize || 0);
            push({
                kind: 'page_load',
                ttfb: Math.round(nav.responseStart),
                dom_ready: Math.round(nav.domContentLoadedEventEnd),
                load: Math.round(nav.loadEventEnd),
                lcp,
                transfer_kb: Math.round(bytes / 1024),
            });
        }, 3000);
    });

    fetch(`${ENDPOINT}/config`, { headers: authHeaders() })
        .then((r) => (r.ok ? r.json() : null)).then(applyLevel).catch(() => {});
    setInterval(() => {
        if (performance.now() - lastFlush >= cfg.flushMs) idle(() => flush());
    }, TICK_MS);
    // Leaving the tab: send now (idle callbacks may never run).
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') flush(true);
    });
    window.addEventListener('pagehide', () => flush(true));
}
